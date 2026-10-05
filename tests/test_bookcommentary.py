import unittest

from pipeline.sources.bookcommentary import parse_review, review_urls


class BookCommentaryTests(unittest.TestCase):
    def test_review_urls_are_absolute_deduplicated_and_same_site(self):
        page = """
        <a href="review-preview/1890/the-cursed">Review</a>
        <a href="https://www.thebookcommentary.com/review-preview/1890/the-cursed">Duplicate</a>
        <a href="https://example.com/review-preview/9/nope">External</a>
        <a href="/order-form">Order form</a>
        """
        self.assertEqual(review_urls(page, "https://www.thebookcommentary.com/reviews"), [
            "https://www.thebookcommentary.com/review-preview/1890/the-cursed",
        ])

    def test_parse_review_uses_book_author_not_reviewer(self):
        page = """
        <html><head><meta property="og:description" content="A science-fiction adventure."></head>
        <body><h1 class="title_text"> The Cursed </h1>
        <table>
          <tr><th>Genre:</th><td>Fiction - Science Fiction</td></tr>
          <tr><th>Author:</th><td>Costi Gurgu</td></tr>
        </table>
        <h4>Reviewed By: <strong>Mariela M. Olsen</strong></h4>
        <h4>Date: <strong>September 23, 2026</strong></h4></body></html>
        """
        result = parse_review(
            page,
            "https://www.thebookcommentary.com/review-preview/1890/the-cursed",
            "Romance",
        )
        self.assertEqual(result["title"], "The Cursed")
        self.assertEqual(result["author"], "Costi Gurgu")
        self.assertNotEqual(result["author"], "Mariela M. Olsen")
        self.assertEqual(result["genre"], "Fiction - Science Fiction")
        self.assertEqual(result["review_date"], "September 23, 2026")

    def test_incomplete_detail_is_skipped(self):
        self.assertIsNone(parse_review("<h1>Untitled</h1>", "https://example.test"))


if __name__ == "__main__":
    unittest.main()