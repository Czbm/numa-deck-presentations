"""Cursor image lookup and rendered preview positioning regression tests."""
import os
import unittest
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
from main import NumaDeckWindow
from preview import PresentationView


class CursorImageTests(unittest.TestCase):
    def test_image_caption_and_repeated_source(self):
        text = ('Text\n\n![First](<C:/Images/a (1).png>)\n*Caption*\n\n'
                'Other text\n\n![Second](<C:/Images/a (1).png>)\n*Second caption*')
        for line, expected in ((0, None), (2, ('C:/Images/a (1).png', 0)),
                               (3, ('C:/Images/a (1).png', 0)), (5, None),
                               (7, ('C:/Images/a (1).png', 1)),
                               (8, ('C:/Images/a (1).png', 1))):
            editor = SimpleNamespace(toPlainText=lambda: text,
                                     textCursor=lambda: SimpleNamespace(blockNumber=lambda: line))
            self.assertEqual(NumaDeckWindow._editor_cursor_image(editor), expected)

    def test_rendered_image_is_centered_not_previous_page(self):
        app = QApplication.instance() or QApplication([])
        view = QWebEngineView()
        view.resize(800, 600)
        view.show()
        loop = QEventLoop()
        loaded = []
        view.loadFinished.connect(lambda ok: (loaded.append(ok), loop.quit()))
        view.setHtml('<!DOCTYPE html><html><body><div id="presentation-container">'
                     '<div style="height:1600px">Previous page</div>'
                     '<img src="file:///C:/Images/example.png" width="400" height="300">'
                     '<div style="height:1600px">Following page</div></div></body></html>')
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(10000)
        loop.exec()
        self.assertEqual(loaded, [True])
        for mode in ('paper', 'scroll'):
            harness = SimpleNamespace(presentation_mode=mode, _loaded=True, web_view=view)
            results = []
            PresentationView.center_on_image(harness, 'C:/Images/example.png',
                                             callback=lambda ok: (results.append(ok), loop.quit()))
            timer.start(10000)
            loop.exec()
            self.assertEqual(results, [True])
            offsets = []
            view.page().runJavaScript(
                "(function(){const r=document.querySelector('img').getBoundingClientRect();"
                "return Math.abs(r.top+r.height/2-document.documentElement.clientHeight/2);})()",
                lambda value: (offsets.append(value), loop.quit()))
            timer.start(10000)
            loop.exec()
            self.assertTrue(offsets)
            self.assertLess(offsets[0], 2)
        timer.stop()
        view.close()


if __name__ == '__main__':
    unittest.main()
