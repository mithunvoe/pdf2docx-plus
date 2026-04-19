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

        # Synthesize fill-in-blank underscore runs from orphan horizontal
        # strokes (common in form documents: "Name: ______"). These are
        # thin, wide horizontal rectangles with no adjacent text; Word has
        # no generic "draw a line in the body" primitive, so we materialise
        # them as underscore glyphs in the text stream.
        fillin_blocks = self._synthesize_fillin_lines(text_blocks)
        if fillin_blocks:
            raw_dict['blocks'].extend(fillin_blocks)

        # Element is a base class processing coordinates, so set rotation matrix globally
        Element.set_rotation_matrix(self.page_engine.rotation_matrix)

        return raw_dict


    def _synthesize_fillin_lines(self, text_blocks):
        """Return synthetic text blocks that visually reproduce orphan
        horizontal vector strokes used as fill-in-blank lines.

        The check is intentionally very strict. Upstream already handles
        strokes that form table grids (via lattice-table detection) and
        strokes that underline real text (via the span semantic-type
        pass). Any false positive here will be injected straight into the
        raw text stream and subsequently break layout/table parsing, so
        we only fire on strokes that look unambiguously like form
        fill-in lines:

        * long and thin in the display CS (>= 100pt wide, <= 1.5pt tall,
          aspect >= 60);
        * no other stroke — horizontal or vertical — within 25pt in any
          direction of the stroke's bbox (rules out table borders and
          adjacent cell edges);
        * no text character runs within 4pt above the stroke along its
          horizontal extent (rules out underlines of real text);
        * the empty horizontal span to the left of the stroke must end
          in a label-like text (ending with ':' or '*'), which is the
          strong cue that this really is a blank-to-be-filled field.

        All analysis happens in DISPLAY CS so rotated landscape pages
        behave the same as portrait ones. Emission bboxes are converted
        back to the un-rotated raw CS because upstream's
        ``Element.__init__`` multiplies every raw bbox by
        ``ROTATION_MATRIX`` before layout.
        """
        try:
            drawings = self.page_engine.get_cdrawings()
        except Exception:
            return []
        if not drawings:
            return []

        page_rotation = self.page_engine.rotation
        rotation_matrix = self.page_engine.rotation_matrix if page_rotation else None
        # inverse of the page rotation, used to convert display CS bboxes
        # back to the un-rotated mediabox CS where raw text lives.
        inverse_rotation = ~rotation_matrix if rotation_matrix is not None else None

        # --- 1. collect every fill rectangle in display CS --------------
        # We need both horizontal and vertical strokes AND general fills
        # (checkboxes, shadings) so isolation checks catch every nearby
        # mark — not just thin strokes.
        all_fills_display = []   # list of fitz.Rect in display CS
        horizontals_display = []  # list of thin-horizontal fitz.Rect in display CS
        for d in drawings:
            rect = d.get('rect')
            if not rect or 'f' not in (d.get('type') or ''):
                continue
            try:
                rx0, ry0, rx1, ry1 = rect
            except Exception:
                continue
            raw_rect = fitz.Rect(rx0, ry0, rx1, ry1)
            disp = raw_rect * rotation_matrix if rotation_matrix is not None else fitz.Rect(raw_rect)
            all_fills_display.append(disp)
            dw = disp.width
            dh = disp.height
            if dh <= 1.5 and dw >= 100.0 and dw >= dh * 60:
                horizontals_display.append(disp)

        if not horizontals_display:
            return []

        # --- 2. display-CS text lines with span text ---------------------
        # We need both the bbox and whether the line ends with a label
        # punctuation character so we can confirm the stroke is a form
        # field. Upstream hands us blocks in un-rotated CS; pre-rotate
        # them for comparison.
        text_lines_display = []
        for block in text_blocks:
            if block.get('type') != 0:
                continue
            for line in block.get('lines', []):
                lb = line.get('bbox')
                if lb is None:
                    continue
                rect = fitz.Rect(*lb)
                if rotation_matrix is not None:
                    rect = rect * rotation_matrix
                line_text = ''
                for span in line.get('spans', []):
                    for ch in span.get('chars', []):
                        c = ch.get('c')
                        if c:
                            line_text += c
                    if 'text' in span and not line_text:
                        line_text += span['text']
                text_lines_display.append((rect, line_text.rstrip()))

        # --- 3. filter horizontals to real fill-in lines ----------------
        synth = []
        ISOLATION = 25.0   # no other stroke within this many pt in display CS
        UNDERLAY_TOL = 4.0  # vertical distance between stroke and text baseline

        for disp in horizontals_display:
            # isolation: any other fill (except self) within 25pt?
            expanded = fitz.Rect(
                disp.x0 - ISOLATION,
                disp.y0 - ISOLATION,
                disp.x1 + ISOLATION,
                disp.y1 + ISOLATION,
            )
            has_neighbour = False
            for other in all_fills_display:
                if other == disp:
                    continue
                # allow duplicates at identical rect (some PDFs draw the
                # same stroke twice); strict equality is safe since we
                # use fitz.Rect equality.
                if abs(other.x0 - disp.x0) < 0.1 and abs(other.y0 - disp.y0) < 0.1 \
                        and abs(other.x1 - disp.x1) < 0.1 and abs(other.y1 - disp.y1) < 0.1:
                    continue
                if expanded.intersects(other):
                    has_neighbour = True
                    break
            if has_neighbour:
                continue

            # underlay: does the stroke sit under real text?
            has_underlay_text = False
            label_text = ''
            for lb, txt in text_lines_display:
                # text above stroke whose baseline is within a few pt
                if abs(lb.y1 - disp.y0) <= UNDERLAY_TOL:
                    inter = max(0.0, min(lb.x1, disp.x1) - max(lb.x0, disp.x0))
                    span_len = min(disp.width, lb.width)
                    if inter > 0 and span_len > 0 and inter >= 0.5 * span_len:
                        has_underlay_text = True
                        break
                # label text to the left of stroke, on approximately the
                # same baseline
                if lb.x1 <= disp.x0 + 1.0 and abs(((lb.y0 + lb.y1) * 0.5) - disp.y0) <= 8.0:
                    if txt and (txt[-1] in ':*;)' or txt.endswith('—') or txt.endswith('–')):
                        label_text = txt
            if has_underlay_text:
                continue
            if not label_text:
                # no obvious "label:" in front — bail. This prevents us
                # from injecting underscores into table rows and other
                # decorative lines that happen to be isolated.
                continue

            # --- 4. emit synthetic underscore text ---------------------
            # Emit in raw CS so Element.ROTATION_MATRIX puts it back in
            # display CS when upstream builds Layout.
            char_w = 5.5
            font_size = 11.0
            count = max(1, int(round(disp.width / char_w)))
            text = '_' * count

            # Compute a display-CS bbox sized to the stroke then map it
            # back to raw CS via the inverse page rotation.
            disp_bbox = fitz.Rect(
                disp.x0,
                disp.y0 - font_size + 1,
                disp.x0 + count * char_w,
                disp.y1 + 1,
            )
            raw_bbox = (disp_bbox * inverse_rotation) if inverse_rotation is not None else disp_bbox
            rx0, ry0, rx1, ry1 = raw_bbox.x0, raw_bbox.y0, raw_bbox.x1, raw_bbox.y1

            # direction is always "visually horizontal left-to-right"
            # after page rotation; pre-rotate (1, 0) to get the raw
            # direction so Line.pure_rotation_matrix() restores it.
            if rotation_matrix is not None:
                raw_dir = fitz.Point(1, 0) * ~fitz.Matrix(
                    rotation_matrix.a, rotation_matrix.b,
                    rotation_matrix.c, rotation_matrix.d, 0, 0)
                direction = (raw_dir.x, raw_dir.y)
            else:
                direction = (1.0, 0.0)

            # individual char bboxes positioned along the stroke axis in
            # display CS, then mapped back. We keep char origins
            # approximate — downstream only uses them for bbox math.
            chars = []
            for i in range(count):
                cdisp = fitz.Rect(
                    disp.x0 + i * char_w,
                    disp.y0 - font_size + 1,
                    disp.x0 + (i + 1) * char_w,
                    disp.y1 + 1,
                )
                crraw = (cdisp * inverse_rotation) if inverse_rotation is not None else cdisp
                chars.append({
                    'c': '_',
                    'origin': (crraw.x0, crraw.y1),
                    'bbox': (crraw.x0, crraw.y0, crraw.x1, crraw.y1),
                })

            synth.append({
                'type': 0,
                'bbox': (rx0, ry0, rx1, ry1),
                'lines': [{
                    'bbox': (rx0, ry0, rx1, ry1),
                    'wmode': 0,
                    'dir': direction,
                    'spans': [{
                        'bbox': (rx0, ry0, rx1, ry1),
                        'size': font_size,
                        'flags': 0,
                        'font': 'Times-Roman',
                        'color': 0,
                        'ascender': 0.9,
                        'descender': -0.2,
                        'text': text,
                        'chars': chars,
                    }],
                }],
            })

        return synth
    

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
