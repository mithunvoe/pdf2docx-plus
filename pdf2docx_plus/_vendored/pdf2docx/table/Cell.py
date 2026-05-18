'''Table Cell object.'''

from docx.shared import Pt
from ..common.Element import Element
from ..layout.Layout import Layout
from ..common import docx
from ..common import constants


# Issue P-2: extra margin (PDF points) added to the cell bbox when
# checking containment of glyph runs.  Real fund-prospectus PDFs centre
# narrow column text slightly outside the inferred cell grid bbox; the
# original strict containment dropped that text, surfacing in the
# converted DOCX as an empty rightmost-column cell (and downstream as a
# missed "Not applicable" / "Up to 0.05 %" deletion in redlines).
_CELL_CONTAINS_TOL = 1.0


class Cell(Layout):
    '''Cell object.'''
    def __init__(self, raw:dict=None):
        raw = raw or {}
        super().__init__()
        self.restore(raw) # restore blocks and shapes

        # more cell properties
        self.bg_color     = raw.get('bg_color', None) # type: int
        self.border_color = raw.get('border_color', (0,0,0,0)) # type: tuple [int]
        self.border_width = raw.get('border_width', (0,0,0,0)) # type: tuple [float]
        self.merged_cells = raw.get('merged_cells', (1,1)) # type: tuple [int]

    def contains(self, e:'Element', threshold:float=1.0):
        '''Issue P-2: loosened cell containment.

        The base ``Element.contains`` uses a strict bbox-intersection
        ratio; on real fund-prospectus PDFs, narrow rightmost-column
        text is centred a hair outside the inferred cell grid bbox and
        therefore reports as "not contained".  The block is then
        dropped, producing an empty ``<w:tc>`` and a missed deletion in
        the downstream redline.

        We relax the check in two ways while preserving the strict
        behaviour everywhere else:

        * The cell's bbox is expanded by ``_CELL_CONTAINS_TOL`` (1 pt)
          on each side before the area check.
        * If the strict area check fails but the candidate element's
          centre point falls inside the expanded cell bbox, the element
          counts as contained.  This recovers text-clusters that cross
          a single boundary by a fraction of a glyph width without
          disturbing assignments where the element clearly sits in a
          different cell.
        '''
        if not e or not bool(e.bbox):
            return False

        expanded = self.bbox + (
            -_CELL_CONTAINS_TOL,
            -_CELL_CONTAINS_TOL,
            _CELL_CONTAINS_TOL,
            _CELL_CONTAINS_TOL,
        )

        # First try the original area-ratio test against the EXPANDED bbox.
        # This is the dominant case and exactly mirrors Element.contains
        # without disturbing its semantics.
        S = e.bbox.get_area()
        if S:
            intersection = expanded & e.bbox
            factor = round(intersection.get_area() / S, 2)
            if factor >= threshold:
                # length check on the expanded bbox
                if expanded.width >= expanded.height:
                    if expanded.width + constants.MINOR_DIST >= e.bbox.width:
                        return True
                else:
                    if expanded.height + constants.MINOR_DIST >= e.bbox.height:
                        return True

        # Centre-containment fallback: if the element's centre is inside
        # the expanded cell bbox, treat as contained.  This rescues
        # narrow centred glyph runs whose bbox crosses the cell edge by
        # a fraction of the glyph width.
        cx = (e.bbox.x0 + e.bbox.x1) / 2.0
        cy = (e.bbox.y0 + e.bbox.y1) / 2.0
        return (
            expanded.x0 <= cx <= expanded.x1
            and expanded.y0 <= cy <= expanded.y1
        )

    def _block_text(self, block):
        '''Get text from a block, always returning a str (for join).'''
        if not hasattr(block, 'text'):
            return '<NEST TABLE>'
        t = block.text
        if t is None:
            return ''
        if isinstance(t, list):
            return '\n'.join(str(x) for x in t)
        return str(t)

    @property
    def text(self):
        '''Text contained in this cell.'''
        if not self: return None
        # NOTE: sub-table may exists in
        # fixme: prev code did `if block.is_text_block`, but sometimes
        # there is no `is_text_block` member; would be good to ensure
        # this member is always present and avoid use of `hasattr()`.
        return '\n'.join([self._block_text(block) for block in self.blocks])
        # return '\n'.join([block.text if hasattr(block, 'text') else '<NEST TABLE>'
        #                         for block in self.blocks])


    @property
    def working_bbox(self):
        '''Inner bbox with border excluded.'''
        x0, y0, x1, y1 = self.bbox
        w_top, w_right, w_bottom, w_left = self.border_width
        bbox = (x0+w_left/2.0, y0+w_top/2.0, x1-w_right/2.0, y1-w_bottom/2.0)
        return Element().update_bbox(bbox).bbox # convert to fitz.Rect


    def store(self):
        if not bool(self): return None
        res = super().store()
        res.update({
            'bg_color': self.bg_color,
            'border_color': self.border_color,
            'border_width': self.border_width,
            'merged_cells': self.merged_cells
        })
        return res


    def plot(self, page):
        '''Plot cell and its sub-layout.'''
        super().plot(page)
        self.blocks.plot(page)


    def make_docx(self, table, indexes):
        '''Set cell style and assign contents.

        Args:
            table (Table): ``python-docx`` table instance.
            indexes (tuple): Row and column indexes, ``(i, j)``.
        '''
        # set cell style, e.g. border, shading, cell width
        self._set_style(table, indexes)

        # ignore merged cells
        if not bool(self):  return

        # merge cells
        n_row, n_col = self.merged_cells
        i, j = indexes
        docx_cell = table.cell(i, j)
        if n_row*n_col != 1 and ((i+n_row-1) * table._column_count + j+n_col-1) < len(table._cells): # check whether index is over length of cells
            _cell = table.cell(i+n_row-1, j+n_col-1)
            try:
                docx_cell.merge(_cell)
            except Exception as e:
                def show(c):
                    return f'[_tc.top={c._tc.top} _tc.bottom={c._tc.bottom}]'
                raise Exception(f'Failed to merge docx_cell={show(docx_cell)} _cell={show(_cell)}. {i=} {j=} {n_row=} {n_col=}') from e

        # ---------------------
        # cell width (cell height is set by row height)
        # ---------------------
        # experience: width of merged cells may change if not setting width for merged cells
        x0, y0, x1, y1 = self.bbox
        docx_cell.width = Pt(x1-x0)

        # insert contents
        # NOTE: there exists an empty paragraph already in each cell, which should be deleted
        # first to avoid unexpected layout. `docx_cell._element.clear_content()` works here.
        # But, docx requires at least one paragraph in each cell, otherwise resulting in a
        # repair error.
        if self.blocks:
            docx_cell._element.clear_content()
            self.blocks.make_docx(docx_cell)


    def _set_style(self, table, indexes):
        '''Set ``python-docx`` cell style, e.g. border, shading, width, row height,
        based on cell block parsed from PDF.

        Args:
            table (Table): ``python-docx`` table object.
            indexes (tuple): ``(i, j)`` index of current cell in table.
        '''
        i, j = indexes
        docx_cell = table.cell(i, j)
        n_row, n_col = self.merged_cells

        # ---------------------
        # border style
        # ---------------------
        # NOTE: border width is specified in eighths of a point, with a minimum value of
        # two (1/4 of a point) and a maximum value of 96 (twelve points)
        keys = ('top', 'end', 'bottom', 'start')
        kwargs = {}
        for k, w, c in zip(keys, self.border_width, self.border_color):
            # skip if width=0 -> will not show in docx
            if not w: continue

            hex_c = f'#{hex(c)[2:].zfill(6)}'
            kwargs[k] = {
                'sz': 8*w, 'val': 'single', 'color': hex_c.upper()
            }

        # merged cells are assumed to have same borders with the main cell
        for m in range(i, i+n_row):
            for n in range(j, j+n_col):
                if len(table._cells) > m * table._column_count + n: # check whether index is over length of cells
                    docx.set_cell_border(table.cell(m, n), **kwargs)

        # ---------------------
        # cell bg-color
        # ---------------------
        if self.bg_color is not None:
            docx.set_cell_shading(docx_cell, self.bg_color)

        # ---------------------
        # clear cell margin
        # ---------------------
        # NOTE: the start position of a table is based on text in cell, rather than
        # left border of table. They're almost aligned if left-margin of cell is zero.
        docx.set_cell_margins(docx_cell, start=0, end=0)

        # set vertical direction if contained text blocks are in vertical direction
        if self.blocks.is_vertical_text:
            docx.set_vertical_cell_direction(docx_cell)
