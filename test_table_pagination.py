"""Exercise real paper pagination in Qt WebEngine, without user documents."""
import os
import json
import re
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
from parser import parse_markdown_to_html
from styles import get_html_template


class TablePaginationTests(unittest.TestCase):
    def test_rows_headers_and_oversized_cell_are_not_clipped(self):
        app = QApplication.instance() or QApplication([])
        long_text = 'LongCellContent ' * 900
        source = '| Key | Description |\n| --- | --- |\n'
        source += ''.join(f'| Row{i} | Description {i} ' + 'wrapped words ' * 20 + '|\n'
                          for i in range(40))
        source += f'| Oversized | {long_text} |\n'
        html = get_html_template(parse_markdown_to_html(source, mode='paper'),
                                 style_mode='paper', font_size=24)
        # Keep the test offline and deterministic; this fixture has no math.
        html = re.sub(r'<script\b[^>]*\bsrc=[^>]*>.*?</script>', '', html, flags=re.S)
        html = re.sub(r'<link\b[^>]*>', '', html)
        view = QWebEngineView()
        view.resize(900, 800)
        view.show()
        loop = QEventLoop()
        loaded = []
        view.loadFinished.connect(lambda ok: (loaded.append(ok), loop.quit()))
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(20000)
        view.setHtml(html)
        loop.exec()
        self.assertEqual(loaded, [True])
        QTimer.singleShot(500, loop.quit)
        loop.exec()
        result = []
        view.page().runJavaScript('''(function(){
            const contents = Array.from(document.querySelectorAll('.print-page-content'));
            const tables = Array.from(document.querySelectorAll('.print-page table'));
            return JSON.stringify({
                paginated: !!document.documentElement.dataset.numaPaperPaginated,
                pages: contents.length,
                clipped: contents.filter(c => c.scrollHeight > c.clientHeight + 2 ||
                    c.scrollWidth > c.clientWidth + 2).length,
                headers: tables.every(t => !!t.querySelector('thead')),
                rows: Array.from(document.querySelectorAll('tbody tr')).map(r =>
                    Array.from(r.cells).map(c => c.textContent.trim()).join('')).join(''),
                descriptions: Array.from(document.querySelectorAll('tbody tr')).map(r =>
                    r.cells[1].textContent).join('')
            });
        })()''', lambda value: (result.append(value), loop.quit()))
        timer.start(20000)
        loop.exec()
        timer.stop()
        view.close()
        self.assertTrue(result)
        evidence = json.loads(result[0])
        self.assertTrue(evidence['paginated'])
        self.assertGreater(evidence['pages'], 2)
        self.assertEqual(evidence['clipped'], 0)
        self.assertTrue(evidence['headers'])
        for i in range(40):
            self.assertIn(f'Row{i}Description {i}', evidence['rows'])
        self.assertIn(long_text.strip(), evidence['descriptions'])


if __name__ == '__main__':
    unittest.main()
