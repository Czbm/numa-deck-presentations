"""Image directives must apply with and without a same-paragraph caption."""

import unittest
from html.parser import HTMLParser

from parser import parse_markdown_to_html


class ImageMarkup(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.figures = []
        self.images = 0
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        if tag == 'figure':
            self.figures.append(dict(attrs))
        if tag == 'img':
            self.images += 1


class ImageDisplayTests(unittest.TestCase):
    def test_directives_with_caption_and_following_content(self):
        for mode in ('slide', 'paper', 'continuous'):
            for frame in ('none', 'plain', 'shadow'):
                for separator in ('\n', '\n\n', '  \n'):
                    with self.subTest(mode=mode, frame=frame, separator=separator):
                        source = (
                            '<!-- numa-image: width=60%, align=left, spacing=compact, '
                            f'orientation=90, color=grayscale, frame={frame} -->\n'
                            '![Example](example.png)' + separator +
                            '*Figure 1. Caption*\n\nFollowing text.\n\n![Other](other.png)'
                        )
                        output = parse_markdown_to_html(source, mode=mode)
                        markup = ImageMarkup(output)
                        self.assertEqual(len(markup.figures), 1)
                        self.assertEqual(markup.images, 2)
                        figure = markup.figures[0]
                        self.assertIn(f'numa-image-frame-{frame}', figure['class'])
                        self.assertIn('numa-image-color-grayscale', figure['class'])
                        self.assertIn('--numa-image-width: 60%', figure['style'])
                        self.assertIn('<em>Figure 1. Caption</em>', output)
                        self.assertIn('Following text.', output)
                        self.assertNotIn('<!-- numa-image:', output)
                        self.assertNotIn('<p><figure', output)

    def test_image_alone(self):
        output = parse_markdown_to_html(
            '<!-- numa-image: width=auto, align=center, spacing=normal, frame=none -->\n'
            '![Example](example.png)', mode='paper'
        )
        self.assertIn('numa-image-frame-none', output)
        self.assertEqual(ImageMarkup(output).images, 1)


if __name__ == '__main__':
    unittest.main()
