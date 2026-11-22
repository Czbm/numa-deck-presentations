"""Render responsive SVGs with actual preview CSS to catch zero-size images."""
import base64
import json
import os
import re
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
from parser import parse_markdown_to_html
from styles import get_html_template


class SvgAutoSizeTests(unittest.TestCase):
    def test_svg_auto_and_explicit_width_keep_visible_aspect_ratio(self):
        app = QApplication.instance() or QApplication([])
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" '
               'viewBox="0 0 1920 1080"><rect width="1920" height="1080" fill="red"/></svg>')
        uri = 'data:image/svg+xml;base64,' + base64.b64encode(svg.encode()).decode()
        png = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='
        view = QWebEngineView()
        view.resize(1000, 800)
        view.show()
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        view.loadFinished.connect(loop.quit)
        try:
            for mode in ('slide', 'scroll', 'paper'):
                for width in ('auto', '60%'):
                    with self.subTest(mode=mode, width=width):
                        md = (f'<!-- numa-image: width={width}, align=center, spacing=normal, frame=none -->\n'
                              f'![SVG]({uri})\n\n'
                              '<!-- numa-image: width=auto, align=center, spacing=normal, frame=none -->\n'
                              f'![Raster]({png})')
                        html = get_html_template(parse_markdown_to_html(md, mode=mode), style_mode=mode)
                        html = re.sub(r'<script\b[^>]*\bsrc=[^>]*>.*?</script>', '', html, flags=re.S)
                        html = re.sub(r'<link\b[^>]*>', '', html)
                        timer.start(10000)
                        view.setHtml(html)
                        loop.exec()
                        QTimer.singleShot(200, loop.quit)
                        loop.exec()
                        results = []
                        view.page().runJavaScript('''JSON.stringify(Array.from(
                            document.querySelectorAll('figure.numa-image img')).map(i => {
                                const r=i.getBoundingClientRect(), s=getComputedStyle(i);
                                return {width:r.width,height:r.height,layoutWidth:i.offsetWidth,loaded:i.complete && i.naturalWidth>0,
                                        border:s.borderTopWidth,shadow:s.boxShadow};
                            }))''', lambda r: (results.append(r), loop.quit()))
                        timer.start(10000)
                        loop.exec()
                        self.assertTrue(results)
                        images = json.loads(results[0])
                        self.assertEqual(len(images), 2)
                        self.assertTrue(all(i['loaded'] for i in images))
                        self.assertGreater(images[0]['width'], 200)
                        self.assertAlmostEqual(images[0]['width'] / images[0]['height'], 16/9, places=2)
                        self.assertEqual(images[0]['border'], '0px')
                        self.assertEqual(images[0]['shadow'], 'none')
                        self.assertEqual(images[1]['layoutWidth'], 1)
        finally:
            timer.stop()
            view.close()


if __name__ == '__main__':
    unittest.main()
