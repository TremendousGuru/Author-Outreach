import datetime
import unittest

from pipeline import scoring


def make_book(**overrides):
    book = {
        'title': 'A Test Novel',
        'amazon_reviews': None,
        'goodreads_ratings': None,
        'ratings_count': None,
        'pub_date': '',
        'first_seen': '2026-10-05T00:00:00+00:00',
    }
    book.update(overrides)
    return book


class BookQualificationTests(unittest.TestCase):
    def test_recently_crawled_old_book_is_not_marked_new(self):
        flags = scoring.evaluate_criteria(
            [make_book(first_seen='2026-10-05T00:00:00+00:00')], {'gaps': []})

        self.assertIsNone(flags['just_launched'])

    def test_recent_publication_and_low_reviews_are_reported_per_book(self):
        recent_date = datetime.datetime.now(datetime.timezone.utc).isoformat()
        book = make_book(pub_date=recent_date, ratings_count=18)

        qualified = scoring.books_meeting_criteria([book], {'gaps': []})

        self.assertEqual(len(qualified), 1)
        self.assertEqual(qualified[0]['book']['title'], 'A Test Novel')
        self.assertIn('0–50 reviews/ratings', qualified[0]['criteria'])
        self.assertIn('recently published or debut', qualified[0]['criteria'])

    def test_review_count_above_threshold_does_not_match(self):
        book = make_book(ratings_count=150, pub_date='2020-01-01')

        qualified = scoring.books_meeting_criteria([book], {'gaps': []})

        self.assertEqual(qualified, [])


if __name__ == '__main__':
    unittest.main()