# -*- coding: utf-8 -*-

'''
A wrapper of PyMuPDF Page as page engine.
'''

import fitz
import logging
from .RawPage import RawPage
from ..image.ImagesExtractor import ImagesExtractor
from ..shape.Paths import Paths
from ..common.constants import FACTOR_A_HALF
from ..common.Element import Element
from ..common.share import (RectType, debug_plot)
from ..common.algorithm import get_area


class RawPageFitz(RawPage):
    '''A wrapper of ``fitz.Page`` to extract source contents.'''

    def extract_raw_dict(self, **settings):
        raw_dict = {}
        if not self.page_engine: return raw_dict

        # actual page size
        # `self.page_engine` is the `fitz.Page`.
        *_, w, h = self.page_engine.rect # always reflecting page rotation
        raw_dict.update({ 'width' : w, 'height': h })
        self.width, self.height = w, h

        # pre-processing layout elements. e.g. text, images and shapes
        text_blocks = self._preprocess_text(**settings)
        raw_dict['blocks'] = text_blocks

        image_blocks = self._preprocess_images(**settings)
        raw_dict['blocks'].extend(image_blocks)
        
        shapes, images =  self._preprocess_shapes(**settings)
        raw_dict['shapes'] = shapes
        raw_dict['blocks'].extend(images)

        hyperlinks = self._preprocess_hyperlinks()
        raw_dict['shapes'].extend(hyperlinks)        
       
        # Element is a base class processing coordinates, so set rotation matrix globally
        Element.set_rotation_matrix(self.page_engine.rotation_matrix)

        return raw_dict
    

    def _preprocess_text(self, **settings):
        '''Extract page text and identify hidden text. 
        
        NOTE: All the coordinates are relative to un-rotated page.

            https://pymupdf.readthedocs.io/en/latest/page.html#modifying-pages
            https://pymupdf.readthedocs.io/en/latest/functions.html#Page.get_texttrace
            https://pymupdf.readthedocs.io/en/latest/textpage.html
        '''
        ocr = settings['ocr']
        if ocr==1: raise SystemExit("OCR feature is planned but not implemented yet.")

        # all text blocks no matter hidden or not
        sort = settings.get('sort')
        raw = self.page_engine.get_text(
                'rawdict',
                flags=0
                    | fitz.TEXT_MEDIABOX_CLIP
                    | fitz.TEXT_CID_FOR_UNKNOWN_UNICODE
                    ,
                sort=sort,
                )
        text_blocks = raw.get('blocks', [])

        # potential UnicodeDecodeError issue when trying to filter hidden text:
        # https://github.com/dothinking/pdf2docx/issues/144
        # https://github.com/dothinking/pdf2docx/issues/155
        try:
            spans = self.page_engine.get_texttrace()
        except SystemError:
            logging.warning('Ignore hidden text checking due to UnicodeDecodeError in upstream library.')
            spans = []
        
        if not spans: return text_blocks

        # ignore hidden text if ocr=0, while extract only hidden text if ocr=2
        if ocr==2:
            f = lambda span: span['type']!=3  # find displayed text and ignore it
        else:
            f = lambda span: span['type']==3  # find hidden text and ignore it
        filtered_spans = list(filter(f, spans))
        
        def span_area(bbox):
            x0, y0, x1, y1 = bbox
            return (x1-x0) * (y1-y0)

        # filter blocks by checking span intersection: mark the entire block if 
        # any span is matched
        blocks = []
        for block in text_blocks:
            intersected = False
            for line in block['lines']:
                for span in line['spans']:
                    for filter_span in filtered_spans:
                        intersected_area = get_area(span['bbox'], filter_span['bbox'])
                        if intersected_area / span_area(span['bbox']) >= FACTOR_A_HALF \
                            and span['font']==filter_span['font']:
                            intersected = True
                            break
                    if intersected: break # skip further span check if found
                if intersected: break     # skip further line check

            # keep block if no any intersection with filtered span
            if not intersected: blocks.append(block)

        return blocks


    def _preprocess_images(self, **settings):
        '''Extract image blocks. Image block extracted by ``page.get_text('rawdict')`` doesn't 
        contain alpha channel data, so it has to get page images by ``page.get_images()`` and 
        then recover them. Note that ``Page.get_images()`` contains each image only once, i.e., 
        ignore duplicated occurrences.
        '''
        # ignore image if ocr-ed pdf: get ocr-ed text only
        if settings['ocr']==2: return []
        
        return ImagesExtractor(self.page_engine).extract_images(settings['clip_image_res_ratio'])


    def _preprocess_shapes(self, **settings):
        '''Identify iso-oriented paths and convert vector graphic paths to pixmap.'''
        paths = self._init_paths(**settings)
        return paths.to_shapes_and_images(
            settings['min_svg_gap_dx'], 
            settings['min_svg_gap_dy'], 
            settings['min_svg_w'], 
            settings['min_svg_h'], 
            settings['clip_image_res_ratio'])
    

    @debug_plot('Source Paths')
    def _init_paths(self, **settings):
        '''Initialize Paths based on drawings extracted with PyMuPDF.

        PyMuPDF >= 1.18 returns ``page.get_cdrawings()`` coordinates in the
        un-rotated page CS (mediabox), so paths on rotated pages are
        mis-aligned relative to text blocks (which pdf2docx rotates through
        ``Element.ROTATION_MATRIX``). To keep every geometry consistent we
        pre-transform the raw drawings into the real (rotated) page CS here
        so Path / Shape classes keep their "already rotated" contract.
        '''
        raw_paths = self.page_engine.get_cdrawings()
        if self.page_engine.rotation:
            raw_paths = _rotate_raw_drawings(raw_paths, self.page_engine.rotation_matrix)
        return Paths(parent=self).restore(raw_paths)
    

    def _preprocess_hyperlinks(self):
        """Get source hyperlink dicts.

        Returns:
            list: A list of source hyperlink dict.
        """
        rotation_matrix = self.page_engine.rotation_matrix if self.page_engine.rotation else None
        hyperlinks = []
        for link in self.page_engine.get_links():
            if link['kind']!=2: continue # consider internet address only
            # ``link['from']`` is un-rotated; rotate so hyperlinks align with
            # rotated text blocks below.
            rect = fitz.Rect(link['from'])
            if rotation_matrix is not None:
                rect = rect * rotation_matrix
            hyperlinks.append({
                'type': RectType.HYPERLINK.value,
                'bbox': tuple(rect),
                'uri' : link['uri']
            })

        return hyperlinks


def _rotate_raw_drawings(raw_paths, rotation_matrix):
    """Transform every coordinate in a raw drawings list to the rotated page CS.

    ``page.get_cdrawings()`` (PyMuPDF >= 1.18) returns coordinates in the
    un-rotated mediabox. Downstream ``Shape`` / ``Stroke`` / ``Hyperlink``
    classes assume real-page CS, so we apply ``rotation_matrix`` once here.
    """
    if not raw_paths:
        return raw_paths

    def _pt(p):
        return tuple(fitz.Point(p) * rotation_matrix)

    def _rect(r):
        rect = fitz.Rect(r) * rotation_matrix
        return (rect.x0, rect.y0, rect.x1, rect.y1)

    def _quad(q):
        # a quad is (ul, ur, ll, lr) of Points
        return tuple(_pt(p) for p in q)

    rotated = []
    for raw in raw_paths:
        new_raw = dict(raw)
        if 'rect' in raw:
            new_raw['rect'] = _rect(raw['rect'])
        items = raw.get('items') or []
        new_items = []
        for item in items:
            op = item[0]
            if op == 'l':
                # (op, p1, p2)
                new_items.append((op, _pt(item[1]), _pt(item[2])))
            elif op == 'c':
                # (op, p1, p2, p3, p4)
                new_items.append((op, _pt(item[1]), _pt(item[2]), _pt(item[3]), _pt(item[4])))
            elif op == 're':
                # (op, rect, orientation)
                if len(item) >= 3:
                    new_items.append((op, _rect(item[1]), item[2]))
                else:
                    new_items.append((op, _rect(item[1])))
            elif op == 'qu':
                new_items.append((op, _quad(item[1])))
            else:
                new_items.append(item)
        new_raw['items'] = new_items
        rotated.append(new_raw)
    return rotated
