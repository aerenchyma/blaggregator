from datetime import datetime

from django.conf import settings
from django.test import TestCase
from django.test.utils import override_settings
import feedparser
from mock import patch

from home.models import Hacker, Blog, Post, User
from .utils import create_posts

N_MAX = settings.MAX_FEED_ENTRIES


@override_settings(AUTHENTICATION_BACKENDS=('django.contrib.auth.backends.ModelBackend', 'home.token_auth.TokenAuthBackend'))
class BaseViewTestCase(TestCase):

    def setUp(self):
        self.setup_test_user()

    def tearDown(self):
        self.clear_db()

    # Helper methods ####

    def clear_db(self):
        User.objects.all().delete()

    def setup_test_user(self):
        self.username = self.password = 'test'
        self.user = User.objects.create_user(self.username)
        self.user.set_password(self.password)
        self.user.save()
        self.hacker = Hacker.objects.create(user_id=self.user.id)

    def login(self):
        """Login as test user."""
        self.client.login(username=self.username, password=self.password)


class FeedsViewTestCase(BaseViewTestCase):

    def test_should_enforce_authentication(self):
        response = self.client.get('/atom.xml')
        self.assertEqual(response.status_code, 404)

        response = self.client.get('/atom.xml', data={'token': ''})
        self.assertEqual(response.status_code, 404)

    def test_should_enforce_token(self):
        self.login()
        response = self.client.get('/new/')
        self.assertEqual(response.status_code, 200)

        response = self.client.get('/atom.xml')
        self.assertEqual(response.status_code, 404)

        response = self.client.get('/atom.xml', data={'token': ''})
        self.assertEqual(response.status_code, 404)

        response = self.client.get('/atom.xml', data={'token': 'BOGUS-TOKEN'})
        self.assertEqual(response.status_code, 404)

    def test_feed_with_no_posts(self):
        self.verify_feed_generation(0)

    def test_feed_with_posts_less_than_max_feed_size(self):
        self.verify_feed_generation(N_MAX - 1)

    def test_feed_with_posts_more_than_max_feed_size(self):
        self.verify_feed_generation(N_MAX * 5)

    # Helper methods ####

    def parse_feed(self, content):
        """Parse feed content and return entries."""
        # FIXME: Would it be a good idea to use feedergrabber?
        return feedparser.parse(content)

    def get_included_excluded_posts(self, posts, entries):
        """Returns the set of included and excluded posts."""

        entry_links = {(entry.title, entry.link) for entry in entries}
        included = []
        excluded = []
        for post in posts:
            if (post.title, post.url) in entry_links:
                included.append(post)
            else:
                excluded.append(post)

        return included, excluded

    # @given(st.integers(min_value=0, max_value=N_MAX * 10))
    # FIXME: Hypothesis' shrinking fails because of random dates on posts
    # generated by faker, not hypothesis
    # FIXME: We could also use py.test to parametrize these tests
    def verify_feed_generation(self, n):
        # Given
        self.clear_db()
        self.login()
        self.setup_test_user()
        posts = create_posts(n)

        # When
        response = self.client.get('/atom.xml', data={'token': self.hacker.token})

        # Then
        self.assertEqual(n, Post.objects.count())
        self.assertEqual(n, len(posts))
        self.assertEqual(200, response.status_code)
        feed = self.parse_feed(response.content)
        entries = feed.entries
        self.assertEqual(min(n, N_MAX), len(entries))
        if n < 1:
            return

        self.assertGreaterEqual(entries[0].updated_parsed,
                                entries[-1].updated_parsed)
        included, excluded = self.get_included_excluded_posts(posts, entries)
        self.assertEqual(len(included), len(entries))
        if not excluded:
            return

        max_excluded_date = max(excluded, key=lambda x: x.date_posted_or_crawled).date_posted_or_crawled
        min_included_date = min(included, key=lambda x: x.date_posted_or_crawled).date_posted_or_crawled
        self.assertGreaterEqual(min_included_date, max_excluded_date)


def empty_feed(url, suggest_feed_url=False):
    return ([], [])


def incorrect_url(url, suggest_feed_url=True):
    return None, [{'feed_url': 'http://jvns.ca/atom.xml'}]


def feed_with_posts(url, suggest_feed_url=True):
    posts = [
        # (post_url, post_title, post_date, post_content),
        ('', 'What happens when you run a rkt container?', datetime(2016, 11, 3), ''),
        ('', 'Service discovery at Stripe', datetime(2016, 10, 31), ''),
        ('', 'A few questions about open source', datetime(2016, 10, 26, 10, 0), ''),
        ('', 'Running containers without Docker', datetime(2016, 10, 26, 21, 0), ''),
        ('', 'A litmus test for job descriptions', datetime(2016, 10, 21), ''),
    ]

    return posts, []


@patch('home.feedergrabber27.feedergrabber', new=empty_feed)
class AddBlogViewTestCase(BaseViewTestCase):

    def test_get_add_blog_requires_login(self):
        # When
        response = self.client.get('/add_blog/', follow=True)

        # Then
        self.assertRedirects(response, '/login/?next=%2Fadd_blog%2F')

    def test_get_add_blog_works(self):
        # Given
        self.login()

        # When
        response = self.client.get('/add_blog/')

        # Then
        self.assertEqual(response.status_code, 200)

    def test_post_add_blog_without_blog_url_barfs(self):
        # Given
        self.login()

        # When
        response = self.client.post('/add_blog/', follow=True)

        # Then
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No feed URL provided')

    def test_post_add_blog_adds_blog(self):
        # Given
        self.login()
        data = {'feed_url': 'https://jvns.ca/atom.xml'}

        # When
        response = self.client.post('/add_blog/', data=data, follow=True)

        # Then
        self.assertRedirects(response, '/new/')
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(Blog.objects.get(feed_url=data['feed_url']))

    def test_post_add_blog_adds_blog_without_schema(self):
        # Given
        self.login()
        data = {'feed_url': 'jvns.ca/atom.xml'}

        # When
        response = self.client.post('/add_blog/', data=data, follow=True)

        # Then
        self.assertRedirects(response, '/new/')
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(Blog.objects.get(feed_url='http://{}'.format(data['feed_url'])))

    def test_post_add_blog_adds_only_once(self):
        # Given
        self.login()
        data = {'feed_url': 'https://jvns.ca/atom.xml'}
        self.client.post('/add_blog/', data=data, follow=True)
        data_ = {'feed_url': 'https://jvns.ca/rss'}

        # When
        response = self.client.post('/add_blog/', data=data_, follow=True)

        # Then
        self.assertRedirects(response, '/new/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(1, Blog.objects.count())

    def test_post_add_blog_adds_different_feeds(self):
        # Given
        self.login()
        data = {'feed_url': 'https://jvns.ca/atom.xml'}
        self.client.post('/add_blog/', data=data, follow=True)
        data_ = {'feed_url': 'https://jvns.ca/tags/blaggregator.xml'}

        # When
        response = self.client.post('/add_blog/', data=data_, follow=True)

        # Then
        self.assertRedirects(response, '/new/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(2, Blog.objects.count())
        self.assertIsNotNone(Blog.objects.get(feed_url=data['feed_url']))

    def test_post_add_blog_suggests_feed_url(self):
        # Given
        self.login()
        data = {'feed_url': 'https://jvns.ca/'}

        # When
        with patch('home.feedergrabber27.feedergrabber', new=incorrect_url):
            response = self.client.post('/add_blog/', data=data, follow=True)

        # Then
        self.assertEqual(0, Blog.objects.count())
        self.assertRedirects(response, '/add_blog/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please use your blog&#39;s feed url")
        self.assertContains(response, "It may be this -- http://jvns.ca/atom.xml")

    def test_post_add_blog_creates_posts(self):
        # Given
        self.login()
        data = {'feed_url': 'https://jvns.ca/'}

        # When
        with patch('home.feedergrabber27.feedergrabber', new=feed_with_posts):
            response = self.client.post('/add_blog/', data=data, follow=True)

        # Then
        self.assertEqual(1, Blog.objects.count())
        self.assertEqual(5, Post.objects.count())
        self.assertRedirects(response, '/new/')
        self.assertEqual(response.status_code, 200)


class DeleteBlogViewTestCase(BaseViewTestCase):

    def test_should_not_delete_blog_not_logged_in(self):
        # Given
        feed_url = 'https://jvns.ca/atom.xml'
        blog = Blog.objects.create(user=self.user, feed_url=feed_url)

        # When
        self.client.get('/delete_blog/%s/' % blog.id)

        # Then
        self.assertEqual(1, Blog.objects.count())

    def test_should_delete_blog(self):
        # Given
        self.login()
        feed_url = 'https://jvns.ca/atom.xml'
        blog = Blog.objects.create(user=self.user, feed_url=feed_url)

        # When
        self.client.get('/delete_blog/%s/' % blog.id)

        # Then
        self.assertEqual(0, Blog.objects.count())
        with self.assertRaises(Blog.DoesNotExist):
            Blog.objects.get(feed_url=feed_url)

    def test_should_not_delete_unknown_blog(self):
        # Given
        self.login()
        feed_url = 'https://jvns.ca/atom.xml'
        blog = Blog.objects.create(user=self.user, feed_url=feed_url)
        self.client.get('/delete_blog/%s/' % blog.id)

        # When
        response = self.client.get('/delete_blog/%s/' % blog.id)

        # Then
        self.assertEqual(404, response.status_code)


class EditBlogViewTestCase(BaseViewTestCase):

    def test_should_not_edit_blog_not_logged_in(self):
        # Given
        feed_url = 'https://jvns.ca/atom.xml'
        blog = Blog.objects.create(user=self.user, feed_url=feed_url)

        # When
        response = self.client.get('/edit_blog/%s/' % blog.id, follow=True)

        # Then
        self.assertRedirects(response, '/login/?next=%2Fedit_blog%2F1%2F')

    def test_should_edit_blog(self):
        # Given
        self.login()
        feed_url = 'https://jvns.ca/atom.xml'
        blog = Blog.objects.create(user=self.user, feed_url=feed_url)
        data = {'feed_url': 'https://jvns.ca/rss', 'stream': 'BLOGGING'}

        # When
        response = self.client.post('/edit_blog/%s/' % blog.id, data=data, follow=True)

        # Then
        self.assertEqual(200, response.status_code)
        with self.assertRaises(Blog.DoesNotExist):
            Blog.objects.get(feed_url=feed_url)
        self.assertIsNotNone(Blog.objects.get(feed_url=data['feed_url']))

    def test_should_show_edit_blog_form(self):
        # Given
        self.login()
        feed_url = 'https://jvns.ca/atom.xml'
        blog = Blog.objects.create(user=self.user, feed_url=feed_url)

        # When
        response = self.client.get('/edit_blog/%s/' % blog.id, follow=True)

        # Then
        self.assertEqual(200, response.status_code)

    def test_should_not_edit_unknown_blog(self):
        # Given
        self.login()
        data = {'feed_url': 'https://jvns.ca/rss', 'stream': 'BLOGGING'}

        # When
        response = self.client.post('/edit_blog/%s/' % 200, data=data, follow=True)

        # Then
        self.assertEqual(404, response.status_code)


class UpdatedAvatarViewTestCase(BaseViewTestCase):

    def test_should_update_avatar_url(self):
        # Given
        self.login()
        expected_url = 'foo.bar'

        def update_user_details(user_id, user):
            self.user.hacker.avatar_url = expected_url
            self.user.hacker.save()

        # When
        with patch('home.views.update_user_details', new=update_user_details):
            response = self.client.get('/updated_avatar/1/', follow=True)

        self.assertEqual(200, response.status_code)
        self.assertEqual(expected_url, response.content)

    def test_should_not_update_unknown_hacker_avatar_url(self):
        # Given
        self.login()
        expected_url = 'foo.bar'

        def update_user_details(user_id, user):
            self.user.hacker.avatar_url = expected_url
            self.user.hacker.save()

        # When
        with patch('home.views.update_user_details', new=update_user_details):
            response = self.client.get('/updated_avatar/200/', follow=True)

        self.assertEqual(404, response.status_code)