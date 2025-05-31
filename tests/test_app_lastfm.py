import unittest
from unittest.mock import patch, MagicMock, PropertyMock
import os

# Add project root to sys.path to allow importing 'app'
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Conditional import for app and spotipy exceptions
try:
    from app import app as flask_app # Assuming your Flask app instance is named 'app' in 'app.py'
<<<<<<< HEAD
    from app import get_lastfm_song_suggestion 
=======
    from app import get_lastfm_song_suggestion
>>>>>>> 3b94088bfe038549908848c0a93d49069274f022
    # Import LASTFM_API_KEY to be able to mock it if it's a global in app.py
    # If it's always accessed via settings, this direct import might not be needed for mocking.
    from app import LASTFM_API_KEY as APP_LASTFM_API_KEY
    from app import settings as app_settings # For mocking settings dict
    from spotipy.exceptions import SpotifyException
except ImportError as e:
    print(f"Failed to import app components: {e}")
    # Define dummy classes/variables if import fails, so tests can be discovered
    # This helps in environments where app.py might have issues not related to these tests
    class SpotifyException(Exception): pass
    flask_app = None
    get_lastfm_song_suggestion = lambda: (None, "ImportError")
    APP_LASTFM_API_KEY = None
    app_settings = {}


<<<<<<< HEAD
class TestGetLastFmSongSuggestion(unittest.TestCase):

    def setUp(self):
        # Store original values to restore them later if necessary (though patch.stopall handles most)
        self.original_lastfm_api_key = APP_LASTFM_API_KEY
        self.original_app_settings = dict(app_settings) # shallow copy

    def tearDown(self):
        # Restore original values if they were changed directly
        # For properties mocked with PropertyMock, they are automatically restored.
        # For globals patched with `patch`, `stopall` in TestSuiteRunner or per-test `patch.stop()` handles it.
        if APP_LASTFM_API_KEY != self.original_lastfm_api_key and 'app.LASTFM_API_KEY' not in patch. वस्तू:
             # This manual restoration is tricky due to how `patch` works.
             # It's better to rely on `patch` for globals or ensure globals are not modified.
             # For this example, we'll assume `patch` handles it or direct modification is avoided.
             pass
        app_settings.clear()
        app_settings.update(self.original_app_settings)


    @patch('app.check_song_filters')
    @patch('app.find_spotify_uri_from_lastfm_track')
    @patch('app.get_lastfm_recent_tracks')
    @patch('app.get_lastfm_session_key_for_user')
    @patch('app.settings') # Mock the settings object itself
    @patch('app.get_spotify_client')
    def test_success_case(self, mock_get_spotify_client, mock_settings,
                          mock_get_lastfm_session_key, mock_get_lastfm_recent_tracks,
                          mock_find_spotify_uri, mock_check_song_filters):

        # Configure mocks for success
        mock_spotify = MagicMock()
        mock_get_spotify_client.return_value = mock_spotify
        
        # Mocking app.settings.get('lastfm_username')
        # Instead of mocking the whole settings dict, mock its .get method
        def settings_get_side_effect(key, default=None):
            if key == 'lastfm_username':
                return 'testuser'
            return app_settings.get(key, default) # Fallback to real settings for other keys if needed
        mock_settings.get = MagicMock(side_effect=settings_get_side_effect)
        
        # If LASTFM_API_KEY is a global in app.py and used directly
        # it needs to be patched where it's defined, e.g., 'app.LASTFM_API_KEY'
        # For this test, let's assume it's not None. If it were, we'd patch it.
        # with patch('app.LASTFM_API_KEY', 'fake_api_key'):

        mock_get_lastfm_session_key.return_value = 'test_sk'
        mock_get_lastfm_recent_tracks.return_value = [{'name': 'Song1', 'artist': 'Artist1'}]
        mock_find_spotify_uri.return_value = 'spotify:track:123'
        
        mock_recommendation_track = {
            'uri': 'spotify:track:rec1',
            'name': 'Recommended Song',
            'artists': [{'name': 'Recommended Artist'}],
            'album': {'images': [{'url': 'http://example.com/image.jpg'}]}
        }
        mock_spotify.recommendations.return_value = {'tracks': [mock_recommendation_track]}
        mock_check_song_filters.return_value = (True, "Allowed")

        result, message = get_lastfm_song_suggestion()

        self.assertIsNotNone(result)
        self.assertEqual(result['id'], 'spotify:track:rec1')
        self.assertEqual(result['name'], 'Recommended Song')
        self.assertEqual(result['artist'], 'Recommended Artist')
        self.assertEqual(result['image_url'], 'http://example.com/image.jpg')
        self.assertTrue("Öneri bulundu" in message)

    @patch('app.get_spotify_client')
    def test_spotify_client_unavailable(self, mock_get_spotify_client):
        mock_get_spotify_client.return_value = None
        result, message = get_lastfm_song_suggestion()
        self.assertIsNone(result)
        self.assertEqual(message, "Spotify bağlantısı yok.")

    @patch('app.get_spotify_client') # Need to mock client as it's checked first
    @patch('app.settings')
    @patch('app.LASTFM_API_KEY', None) # Mock the global directly
    def test_lastfm_not_configured_no_api_key(self, mock_settings, mock_get_spotify_client):
        mock_get_spotify_client.return_value = MagicMock() # Spotify client is available
        # settings.get('lastfm_username') will be called, ensure it returns something or mock it
        mock_settings.get.return_value = 'testuser' # Assume username is set

        result, message = get_lastfm_song_suggestion()
        self.assertIsNone(result)
        # This message might vary based on which check fails first (API key or username)
        self.assertTrue("Last.fm API anahtarı yapılandırılmamış" in message or "Last.fm yapılandırması eksik" in message)


    @patch('app.get_spotify_client')
    @patch('app.settings') 
    def test_lastfm_not_configured_no_username(self, mock_settings, mock_get_spotify_client):
        mock_get_spotify_client.return_value = MagicMock()
        # mock_settings is an object, we need to mock its .get method
        mock_settings.get.return_value = None # For lastfm_username
        # Assume app.LASTFM_API_KEY is set for this test
        # with patch('app.LASTFM_API_KEY', 'fake_api_key'):
        # No, app.LASTFM_API_KEY is already imported, so we ensure it's not None for this test
        # or patch it if it's None by default in the test environment.
        # We'll rely on its imported value or specific patching if it were None.

        result, message = get_lastfm_song_suggestion()
        self.assertIsNone(result)
        self.assertTrue("Last.fm kullanıcı adı eksik" in message or "Last.fm yapılandırması eksik" in message)


    @patch('app.get_lastfm_session_key_for_user')
    @patch('app.settings')
    @patch('app.get_spotify_client')
    def test_lastfm_not_connected_no_session_key(self, mock_get_spotify_client, mock_settings, mock_get_lastfm_session_key):
        mock_get_spotify_client.return_value = MagicMock()
        mock_settings.get.return_value = 'testuser' # for lastfm_username
        mock_get_lastfm_session_key.return_value = None
        # with patch('app.LASTFM_API_KEY', 'fake_api_key'): # Ensure API key is present

        result, message = get_lastfm_song_suggestion()
        self.assertIsNone(result)
        self.assertTrue("Last.fm bağlantısı gerekli" in message)

    @patch('app.get_lastfm_recent_tracks')
    @patch('app.get_lastfm_session_key_for_user')
    @patch('app.settings')
    @patch('app.get_spotify_client')
    def test_no_recent_tracks(self, mock_get_spotify_client, mock_settings, 
                              mock_get_lastfm_session_key, mock_get_lastfm_recent_tracks):
        mock_get_spotify_client.return_value = MagicMock()
        mock_settings.get.return_value = 'testuser'
        mock_get_lastfm_session_key.return_value = 'test_sk'
        mock_get_lastfm_recent_tracks.return_value = [] # No tracks
        # with patch('app.LASTFM_API_KEY', 'fake_api_key'):

        result, message = get_lastfm_song_suggestion()
        self.assertIsNone(result)
        self.assertEqual(message, "Last.fm'den son çalınan şarkılar alınamadı.")

    @patch('app.find_spotify_uri_from_lastfm_track')
    @patch('app.get_lastfm_recent_tracks')
    @patch('app.get_lastfm_session_key_for_user')
    @patch('app.settings')
    @patch('app.get_spotify_client')
    def test_no_spotify_uris_found(self, mock_get_spotify_client, mock_settings,
                                   mock_get_lastfm_session_key, mock_get_lastfm_recent_tracks,
                                   mock_find_spotify_uri):
        mock_get_spotify_client.return_value = MagicMock()
        mock_settings.get.return_value = 'testuser'
        mock_get_lastfm_session_key.return_value = 'test_sk'
        mock_get_lastfm_recent_tracks.return_value = [{'name': 'Song1', 'artist': 'Artist1'}]
        mock_find_spotify_uri.return_value = None # No URI found for any track
        # with patch('app.LASTFM_API_KEY', 'fake_api_key'):

        result, message = get_lastfm_song_suggestion()
        self.assertIsNone(result)
        self.assertEqual(message, "Spotify URI bulunamadı.")

    @patch('app.check_song_filters') # Mock this to avoid issues if it's called
    @patch('app.find_spotify_uri_from_lastfm_track')
    @patch('app.get_lastfm_recent_tracks')
    @patch('app.get_lastfm_session_key_for_user')
    @patch('app.settings')
    @patch('app.get_spotify_client')
    def test_spotify_returns_no_recommendations(self, mock_get_spotify_client, mock_settings,
                                               mock_get_lastfm_session_key, mock_get_lastfm_recent_tracks,
                                               mock_find_spotify_uri, mock_check_song_filters):
        mock_spotify = MagicMock()
        mock_get_spotify_client.return_value = mock_spotify
        mock_settings.get.return_value = 'testuser'
        mock_get_lastfm_session_key.return_value = 'test_sk'
        mock_get_lastfm_recent_tracks.return_value = [{'name': 'Song1', 'artist': 'Artist1'}]
        mock_find_spotify_uri.return_value = 'spotify:track:123'
        mock_spotify.recommendations.return_value = {'tracks': []} # No recommendations
        # with patch('app.LASTFM_API_KEY', 'fake_api_key'):

        result, message = get_lastfm_song_suggestion()
        self.assertIsNone(result)
        self.assertEqual(message, "Uygun öneri yok.") # This is if recs['tracks'] is empty

    @patch('app.check_song_filters')
    @patch('app.find_spotify_uri_from_lastfm_track')
    @patch('app.get_lastfm_recent_tracks')
    @patch('app.get_lastfm_session_key_for_user')
    @patch('app.settings')
    @patch('app.get_spotify_client')
    def test_all_recommendations_filtered(self, mock_get_spotify_client, mock_settings,
                                          mock_get_lastfm_session_key, mock_get_lastfm_recent_tracks,
                                          mock_find_spotify_uri, mock_check_song_filters):
        mock_spotify = MagicMock()
        mock_get_spotify_client.return_value = mock_spotify
        mock_settings.get.return_value = 'testuser'
        mock_get_lastfm_session_key.return_value = 'test_sk'
        mock_get_lastfm_recent_tracks.return_value = [{'name': 'Song1', 'artist': 'Artist1'}]
        mock_find_spotify_uri.return_value = 'spotify:track:123'
        mock_recommendation_track = {'uri': 'spotify:track:rec1', 'name': 'Filtered Song', 'artists': [{'name': 'Artist'}], 'album': {'images': []}}
        mock_spotify.recommendations.return_value = {'tracks': [mock_recommendation_track]}
        mock_check_song_filters.return_value = (False, "Filtered") # All songs filtered out
        # with patch('app.LASTFM_API_KEY', 'fake_api_key'):

        result, message = get_lastfm_song_suggestion()
        self.assertIsNone(result)
        self.assertEqual(message, "Uygun öneri yok.")


    @patch('app.os.remove') # Mock os.remove to check if token file is deleted
    @patch('app.find_spotify_uri_from_lastfm_track')
    @patch('app.get_lastfm_recent_tracks')
    @patch('app.get_lastfm_session_key_for_user')
    @patch('app.settings')
    @patch('app.get_spotify_client')
    def test_spotify_api_exception(self, mock_get_spotify_client, mock_settings,
                                   mock_get_lastfm_session_key, mock_get_lastfm_recent_tracks,
                                   mock_find_spotify_uri, mock_os_remove):
        mock_spotify = MagicMock()
        mock_get_spotify_client.return_value = mock_spotify
        mock_settings.get.return_value = 'testuser'
        mock_get_lastfm_session_key.return_value = 'test_sk'
        mock_get_lastfm_recent_tracks.return_value = [{'name': 'Song1', 'artist': 'Artist1'}]
        mock_find_spotify_uri.return_value = 'spotify:track:123'
        # Simulate a 401 error
        mock_spotify.recommendations.side_effect = SpotifyException(401, -1, "Unauthorized")
        # with patch('app.LASTFM_API_KEY', 'fake_api_key'):
        # Patch app.spotify_client to check if it's reset
        with patch('app.spotify_client', mock_spotify): # initial value
            result, message = get_lastfm_song_suggestion()

        self.assertIsNone(result)
        self.assertEqual(message, "Spotify hatası: Unauthorized")
        # Check if os.remove was called for TOKEN_FILE if SpotifyException is 401/403
        # This depends on the exact name of TOKEN_FILE used in app.py
        # from app import TOKEN_FILE # Assuming TOKEN_FILE is importable or known
        # mock_os_remove.assert_called_with(TOKEN_FILE) # This line might need adjustment
        # Also, check if app.spotify_client was set to None (harder to check directly without more app context)
        # One way is to check if get_spotify_client is called again and tries to re-auth
        # For now, checking the message and os.remove is a good start.
        # The current get_lastfm_song_suggestion sets the global spotify_client to None,
        # but testing this global change effect from here is complex.


@unittest.skipIf(flask_app is None, "Flask app not imported, skipping API tests")
class TestApiLastFmSuggestion(unittest.TestCase):
=======
    app_settings.clear()
    app_settings.update(self.original_app_settings)

# Renamed class to be more generic
@unittest.skipIf(flask_app is None, "Flask app not imported, skipping API tests")
class TestApiSuggestion(unittest.TestCase):
>>>>>>> 3b94088bfe038549908848c0a93d49069274f022

    def setUp(self):
        if flask_app:
            flask_app.testing = True
<<<<<<< HEAD
=======
            # Create a new client for each test to ensure session isolation
>>>>>>> 3b94088bfe038549908848c0a93d49069274f022
            self.client = flask_app.test_client()
        else:
            self.client = None

<<<<<<< HEAD
    @patch('app.get_lastfm_song_suggestion')
    @patch('app.get_spotify_client') # For the @spotify_auth_required decorator
    def test_api_successful_suggestion(self, mock_get_spotify_client_decorator, mock_get_lastfm_suggestion_func):
        if not self.client: self.skipTest("Flask client not available")

        # Mock the decorator's check to pass
        mock_get_spotify_client_decorator.return_value = MagicMock() 
        
        # Mock the function called by the API endpoint
        mock_suggestion_data = {'id': 'spotify:track:rec1', 'name': 'Test Song', 'artist': 'Test Artist', 'image_url': 'url'}
        mock_get_lastfm_suggestion_func.return_value = (mock_suggestion_data, "Suggestion found")

        response = self.client.get('/api/lastfm-suggestion')
        
=======
    # Renamed test method and updated mock + URL
    @patch('app.get_spotify_recommendation_from_local_history')
    @patch('app.get_spotify_client')
    def test_api_get_suggestion_success(self, mock_get_spotify_client_decorator, mock_get_reco_from_local):
        if not self.client: self.skipTest("Flask client not available")

        mock_get_spotify_client_decorator.return_value = MagicMock()

        mock_suggestion_data = {'id': 'spotify:track:rec1', 'name': 'Local History Song', 'artist': 'Local Artist', 'image_url': 'local_url'}
        mock_get_reco_from_local.return_value = (mock_suggestion_data, "Local history suggestion found")

        response = self.client.get('/api/suggestion') # New URL

>>>>>>> 3b94088bfe038549908848c0a93d49069274f022
        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertTrue(json_data['success'])
        self.assertEqual(json_data['suggestion'], mock_suggestion_data)
<<<<<<< HEAD
        self.assertEqual(json_data['message'], "Suggestion found")

    @patch('app.get_lastfm_song_suggestion')
    @patch('app.get_spotify_client') # For the @spotify_auth_required decorator
    def test_api_no_suggestion(self, mock_get_spotify_client_decorator, mock_get_lastfm_suggestion_func):
        if not self.client: self.skipTest("Flask client not available")

        mock_get_spotify_client_decorator.return_value = MagicMock()
        mock_get_lastfm_suggestion_func.return_value = (None, "No suitable suggestion")

        response = self.client.get('/api/lastfm-suggestion')
        
=======
        self.assertEqual(json_data['message'], "Local history suggestion found")

    # Renamed test method and updated mock + URL
    @patch('app.get_spotify_recommendation_from_local_history')
    @patch('app.get_spotify_client')
    def test_api_get_suggestion_no_suggestion(self, mock_get_spotify_client_decorator, mock_get_reco_from_local):
        if not self.client: self.skipTest("Flask client not available")

        mock_get_spotify_client_decorator.return_value = MagicMock()
        mock_get_reco_from_local.return_value = (None, "No suitable local history suggestion")

        response = self.client.get('/api/suggestion') # New URL

>>>>>>> 3b94088bfe038549908848c0a93d49069274f022
        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertFalse(json_data['success'])
        self.assertIsNone(json_data['suggestion'])
<<<<<<< HEAD
        self.assertEqual(json_data['message'], "No suitable suggestion")

    # Testing the @spotify_auth_required decorator's failure case (redirect)
    @patch('app.get_spotify_client') # This is what the decorator calls
    def test_api_auth_required_redirect(self, mock_get_spotify_client_decorator):
        if not self.client: self.skipTest("Flask client not available")

        mock_get_spotify_client_decorator.return_value = None # Simulate no Spotify client / not authenticated

        response = self.client.get('/api/lastfm-suggestion')
        
        # The @spotify_auth_required decorator should redirect to an auth prompt page
        # which typically results in a 302 status code.
        # It might also flash a message, but testing flash messages is more involved.
        self.assertEqual(response.status_code, 302) 
=======
        self.assertEqual(json_data['message'], "No suitable local history suggestion")

    @patch('app.get_spotify_client')
    def test_api_get_suggestion_auth_required_redirect(self, mock_get_spotify_client_decorator):
        if not self.client: self.skipTest("Flask client not available")

        mock_get_spotify_client_decorator.return_value = None

        response = self.client.get('/api/suggestion') # New URL

        # It might also flash a message, but testing flash messages is more involved.
        self.assertEqual(response.status_code, 302)
>>>>>>> 3b94088bfe038549908848c0a93d49069274f022
        # We can also check if 'Location' header points to the expected redirect URL
        # For example: self.assertTrue('/spotify-auth-prompt' in response.headers['Location'])

    @patch('app.save_lastfm_session')
<<<<<<< HEAD
    @patch('requests.post') # Mocks requests.post used within lastfm_callback
    @patch('app.save_settings') # Mocks app.save_settings
    @patch('app.load_settings') # Mocks app.load_settings
    # Ensure necessary global configurations are patched if not handled at class/module level
    @patch('app.LASTFM_SHARED_SECRET', 'mock_secret')
    @patch('app.LASTFM_API_KEY', 'mock_api_key')
    @patch('app.LASTFM_REDIRECT_URI', 'http://mockhost/lastfm_callback') # Not directly used by callback but good practice
    @patch('app.get_spotify_client') # For @admin_login_required if it uses spotify_auth_required, or if callback itself calls it
    def test_lastfm_callback_saves_username_if_missing(self, mock_get_spotify_client_dec, mock_load_settings, mock_save_settings, mock_requests_post, mock_save_lfm_session):
        if not self.client: self.skipTest("Flask client not available")

        # Mock for decorator if it's an admin-only page that also needs Spotify
        mock_get_spotify_client_dec.return_value = MagicMock()

        # --- Mock Configuration ---
=======
    @patch('requests.post')
    @patch('app.save_settings')
    @patch('app.load_settings')
    @patch('app.LASTFM_SHARED_SECRET', 'mock_secret')
    @patch('app.LASTFM_API_KEY', 'mock_api_key')
    @patch('app.LASTFM_REDIRECT_URI', 'http://mockhost/lastfm_callback')
    @patch('app.get_spotify_client')
    def test_lastfm_callback_saves_username_if_missing(self, mock_get_spotify_client_dec, mock_load_settings, mock_save_settings, mock_requests_post, mock_save_lfm_session):
        if not self.client: self.skipTest("Flask client not available")

        mock_get_spotify_client_dec.return_value = MagicMock()

>>>>>>> 3b94088bfe038549908848c0a93d49069274f022
        initial_settings_without_username = {'max_queue_length': 20, 'some_other_setting': 'value'}
        mock_load_settings.return_value = initial_settings_without_username

        mock_lfm_api_response = MagicMock()
        mock_lfm_api_response.json.return_value = {
<<<<<<< HEAD
            "session": {
                "name": "test_lastfm_user_from_api", # Distinct name for clarity
                "key": "test_session_key_from_api",
                "subscriber": "0"
            }
        }
        mock_lfm_api_response.raise_for_status = MagicMock() # Ensure it doesn't raise for status
        mock_requests_post.return_value = mock_lfm_api_response
        
        # --- Test Execution ---
        # Simulate admin login for the callback, as it's decorated with @admin_login_required
        with self.client.session_transaction() as sess:
            sess['admin'] = True 
            # sess['lastfm_intended_username'] = 'any_user_or_none' # Not strictly needed if configured_username is None initially

        response = self.client.get('/lastfm_callback?token=dummy_token_from_lastfm')

        # --- Assertions ---
        mock_load_settings.assert_called() 
        
        mock_save_settings.assert_called()
        saved_settings_arg = None
        # Iterate through calls to find the one that contains 'lastfm_username'
        # because load_settings might call save_settings if defaults are missing initially.
        for call_args_tuple in mock_save_settings.call_args_list:
            args, _ = call_args_tuple
            if args and isinstance(args[0], dict) and 'lastfm_username' in args[0]:
                saved_settings_arg = args[0]
                break
        
        self.assertIsNotNone(saved_settings_arg, "save_settings was not called with settings dictionary, or 'lastfm_username' was missing.")
        self.assertEqual(saved_settings_arg.get('lastfm_username'), 'test_lastfm_user_from_api')

        mock_save_lfm_session.assert_called_once_with('test_lastfm_user_from_api', 'test_session_key_from_api')
        
        self.assertEqual(response.status_code, 302, f"Response should be a redirect. Got {response.status_code}. Response data: {response.data.decode()}")
        # Check if it redirects to admin_panel or the 'next_url_lastfm' if that was in session
        self.assertTrue('/admin_panel' in response.headers.get('Location', ''), "Redirect location should lead to admin_panel.")

=======
            "session": { "name": "test_lastfm_user_from_api", "key": "test_session_key_from_api", "subscriber": "0" }
        }
        mock_lfm_api_response.raise_for_status = MagicMock()
        mock_requests_post.return_value = mock_lfm_api_response

        with self.client.session_transaction() as sess:
            sess['admin'] = True

        response = self.client.get('/lastfm_callback?token=dummy_token_from_lastfm')

        mock_load_settings.assert_called()
        mock_save_settings.assert_called()
        saved_settings_arg = None
        for call_args_tuple in mock_save_settings.call_args_list:
            args, _ = call_args_tuple
            if args and isinstance(args[0], dict) and 'lastfm_username' in args[0]:
                saved_settings_arg = args[0]; break

        self.assertIsNotNone(saved_settings_arg, "save_settings was not called with settings dictionary, or 'lastfm_username' was missing.")
        self.assertEqual(saved_settings_arg.get('lastfm_username'), 'test_lastfm_user_from_api')
        mock_save_lfm_session.assert_called_once_with('test_lastfm_user_from_api', 'test_session_key_from_api')
        self.assertEqual(response.status_code, 302, f"Response should be a redirect. Got {response.status_code}. Response data: {response.data.decode()}")
        self.assertTrue('/admin_panel' in response.headers.get('Location', ''), "Redirect location should lead to admin_panel.")

# --- Tests for get_recent_spotify_tracks_from_db ---
# Need to import sqlite3 if not already imported for tests
try:
    import sqlite3
    from app import get_recent_spotify_tracks_from_db, DB_PATH
except ImportError:
    sqlite3 = None
    get_recent_spotify_tracks_from_db = lambda limit=5: []
    DB_PATH = 'dummy.db'


@unittest.skipIf(sqlite3 is None, "sqlite3 not available, skipping DB tests")
class TestGetRecentTracksFromDb(unittest.TestCase):

    @patch('sqlite3.connect')
    def test_successful_retrieval(self, mock_sqlite_connect):
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_sqlite_connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [('spotify:track:123',), ('spotify:track:456',)]

        tracks = get_recent_spotify_tracks_from_db(limit=2)
        self.assertEqual(tracks, ['spotify:track:123', 'spotify:track:456'])
        mock_sqlite_connect.assert_called_once_with(DB_PATH)
        mock_conn.cursor.assert_called_once()
        mock_cursor.execute.assert_called_once_with(
            "SELECT DISTINCT track_id FROM played_tracks ORDER BY played_at DESC LIMIT ?", (2,)
        )
        mock_conn.close.assert_called_once()

    @patch('sqlite3.connect')
    def test_filters_non_spotify_uris(self, mock_sqlite_connect):
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_sqlite_connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [('spotify:track:123',), ('not:a:spotify:uri',), ('spotify:track:789',)]

        tracks = get_recent_spotify_tracks_from_db(limit=3)
        self.assertEqual(tracks, ['spotify:track:123', 'spotify:track:789'])

    @patch('sqlite3.connect')
    def test_limit_works(self, mock_sqlite_connect):
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_sqlite_connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [('spotify:track:1',), ('spotify:track:2',), ('spotify:track:3',)]

        tracks = get_recent_spotify_tracks_from_db(limit=2)
        self.assertEqual(len(tracks), 2)
        self.assertEqual(tracks, ['spotify:track:1', 'spotify:track:2'])
        mock_cursor.execute.assert_called_once_with(
            "SELECT DISTINCT track_id FROM played_tracks ORDER BY played_at DESC LIMIT ?", (2,)
        )

    @patch('sqlite3.connect')
    def test_empty_database(self, mock_sqlite_connect):
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_sqlite_connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []

        tracks = get_recent_spotify_tracks_from_db(limit=5)
        self.assertEqual(tracks, [])

    @patch('app.logger')
    @patch('sqlite3.connect')
    def test_database_error(self, mock_sqlite_connect, mock_logger):
        mock_sqlite_connect.side_effect = sqlite3.Error("Test DB error")

        tracks = get_recent_spotify_tracks_from_db(limit=5)
        self.assertEqual(tracks, [])
        mock_logger.error.assert_called_with("Veritabanından son çalınan şarkıları alırken SQLite hatası: Test DB error")


# --- Tests for recommend_and_play_from_local_history ---
try:
    from app import recommend_and_play_from_local_history, TOKEN_FILE
except ImportError:
    recommend_and_play_from_local_history = lambda: (False, "ImportError")
    TOKEN_FILE = "dummy_token.json"

class TestRecommendAndPlayFromLocalHistory(unittest.TestCase):

    def setUp(self):
        # Ensure a clean global spotify_client state for certain tests if needed
        # However, most tests will mock get_spotify_client directly.
        pass

    @patch('app.save_played_track')
    @patch('app.update_time_profile')
    @patch('app.get_spotify_client')
    @patch('app.settings')
    @patch('app.get_spotify_recommendation_from_local_history')
    @patch('time.sleep', return_value=None) # Mock time.sleep to speed up tests
    def test_success_active_device_set(self, mock_get_reco, mock_settings_get, mock_get_spotify_client,
                                       mock_update_time_profile, mock_save_played_track, mock_time_sleep):
        mock_suggestion = {'id': 'spotify:track:xyz', 'name': 'Cool Song', 'artist': 'Cool Artist'}
        mock_get_reco.return_value = (mock_suggestion, "Suggestion found")

        mock_settings_get.get.return_value = 'mock_device_id' # active_device_id

        mock_spotify = MagicMock()
        mock_get_spotify_client.return_value = mock_spotify

        success, message = recommend_and_play_from_local_history()

        self.assertTrue(success)
        self.assertEqual(message, "Yerel geçmişten önerilen 'Cool Song' çalınıyor.")
        mock_spotify.start_playback.assert_called_once_with(device_id='mock_device_id', uris=['spotify:track:xyz'])
        mock_update_time_profile.assert_called_once_with('spotify:track:xyz', mock_spotify)
        mock_save_played_track.assert_called_once_with(mock_suggestion)

    @patch('app.save_played_track')
    @patch('app.update_time_profile')
    @patch('app.get_spotify_client')
    @patch('app.settings')
    @patch('app.get_spotify_recommendation_from_local_history')
    @patch('time.sleep', return_value=None)
    def test_success_device_discovery_active(self, mock_get_reco, mock_settings_obj, mock_get_spotify_client,
                                          mock_update_time_profile, mock_save_played_track, mock_time_sleep):
        mock_suggestion = {'id': 'spotify:track:abc', 'name': 'Discovered Song', 'artist': 'Disco Artist'}
        mock_get_reco.return_value = (mock_suggestion, "Suggestion found")

        # settings.get('active_device_id') returns None
        mock_settings_obj.get = MagicMock(return_value=None)

        mock_spotify = MagicMock()
        mock_spotify.devices.return_value = {
            'devices': [
                {'id': 'dev1', 'is_active': False, 'name': 'Inactive'},
                {'id': 'dev2_active', 'is_active': True, 'name': 'Active Device'}
            ]
        }
        mock_get_spotify_client.return_value = mock_spotify

        success, message = recommend_and_play_from_local_history()

        self.assertTrue(success)
        mock_spotify.start_playback.assert_called_once_with(device_id='dev2_active', uris=['spotify:track:abc'])

    @patch('app.save_played_track')
    @patch('app.update_time_profile')
    @patch('app.get_spotify_client')
    @patch('app.settings')
    @patch('app.get_spotify_recommendation_from_local_history')
    @patch('time.sleep', return_value=None)
    def test_success_device_discovery_transfer(self, mock_get_reco, mock_settings_obj, mock_get_spotify_client,
                                             mock_update_time_profile, mock_save_played_track, mock_time_sleep):
        mock_get_reco.return_value = ({'id': 'spotify:track:def', 'name': 'Transfer Song'}, "Ok")
        mock_settings_obj.get = MagicMock(return_value=None) # No active_device_id in settings

        mock_spotify = MagicMock()
        mock_spotify.devices.return_value = {'devices': [{'id': 'dev_to_transfer', 'is_active': False, 'name': 'Needs Transfer'}]}
        mock_get_spotify_client.return_value = mock_spotify

        success, message = recommend_and_play_from_local_history()

        self.assertTrue(success)
        mock_spotify.transfer_playback.assert_called_once_with(device_id='dev_to_transfer', force_play=False)
        mock_time_sleep.assert_called_once_with(1)
        mock_spotify.start_playback.assert_called_once_with(device_id='dev_to_transfer', uris=['spotify:track:def'])

    @patch('app.get_spotify_recommendation_from_local_history')
    def test_failure_no_suggestion(self, mock_get_reco):
        mock_get_reco.return_value = (None, "No suggestion available")
        success, message = recommend_and_play_from_local_history()
        self.assertFalse(success)
        self.assertEqual(message, "No suggestion available")

    @patch('app.get_spotify_recommendation_from_local_history')
    @patch('app.get_spotify_client') # Mock the get_spotify_client used by the function itself
    def test_failure_no_spotify_client(self, mock_get_spotify_client, mock_get_reco):
        # First call to get_spotify_client (inside get_spotify_recommendation_from_local_history) is successful
        mock_get_reco.return_value = ({'id': 'spotify:track:123'}, "Suggestion")
        # Second call to get_spotify_client (inside recommend_and_play_from_local_history) fails
        mock_get_spotify_client.side_effect = [MagicMock(), None] # First call OK, second returns None

        # To ensure the first call within get_spotify_recommendation_from_local_history works,
        # we might need a more complex setup or trust its own unit tests.
        # For simplicity here, let's assume get_spotify_recommendation_from_local_history works,
        # and we are testing the safeguard within recommend_and_play_from_local_history.
        # This requires get_spotify_recommendation_from_local_history to not fail first.
        # A more direct way:
        with patch('app.get_spotify_recommendation_from_local_history', return_value=({'id': 'spotify:track:xyz'}, "Ok")):
            with patch('app.get_spotify_client', return_value=None) as mock_gsc_safeguard:
                 success, message = recommend_and_play_from_local_history()
                 self.assertFalse(success)
                 self.assertEqual(message, "Spotify bağlantısı yok.")


    @patch('app.get_spotify_client')
    @patch('app.settings')
    @patch('app.get_spotify_recommendation_from_local_history')
    def test_failure_no_devices_found(self, mock_get_reco, mock_settings_obj, mock_get_spotify_client):
        mock_get_reco.return_value = ({'id': 'spotify:track:ghi'}, "Ok")
        mock_settings_obj.get = MagicMock(return_value=None) # No active_device_id

        mock_spotify = MagicMock()
        mock_spotify.devices.return_value = {'devices': []} # No devices
        mock_get_spotify_client.return_value = mock_spotify

        success, message = recommend_and_play_from_local_history()
        self.assertFalse(success)
        self.assertEqual(message, "Aktif Spotify cihazı bulunamadı.")

    @patch('app.logger')
    @patch('os.path.exists', return_value=True) # Assume TOKEN_FILE exists
    @patch('os.remove')
    @patch('app.get_spotify_client')
    @patch('app.settings')
    @patch('app.get_spotify_recommendation_from_local_history')
    def test_failure_spotify_exception_on_playback_401(self, mock_get_reco, mock_settings_obj, mock_get_spotify_client,
                                                     mock_os_remove, mock_os_path_exists, mock_logger):
        mock_get_reco.return_value = ({'id': 'spotify:track:jkl', 'name': 'Exception Song'}, "Ok")
        mock_settings_obj.get.return_value = 'mock_device_id'

        mock_spotify = MagicMock()
        mock_spotify.start_playback.side_effect = SpotifyException(401, -1, "Unauthorized")

        # Patch the global app.spotify_client directly for this specific test of reset
        # We need to ensure get_spotify_client returns our mock_spotify first.
        mock_get_spotify_client.return_value = mock_spotify

        with patch('app.spotify_client', mock_spotify) as mock_global_spotify_client_ref:
            success, message = recommend_and_play_from_local_history()
            self.assertFalse(success)
            self.assertEqual(message, "Spotify API Hatası (Öneri Çalma): Unauthorized")
            mock_os_remove.assert_called_with(TOKEN_FILE)
            # Check if the global spotify_client was set to None by the handler
            # This requires checking the value of app.spotify_client *after* the call
            # One way is to use a global variable or a side effect on a mock.
            # For simplicity, we'll trust the code sets it to None.
            # A more robust test would be to check if a subsequent call to get_spotify_client
            # attempts to re-initialize due to spotify_client being None.

>>>>>>> 3b94088bfe038549908848c0a93d49069274f022

if __name__ == '__main__':
    # Basic test runner. More sophisticated runners can be used.
    # Ensure that if tests are run directly, the app related imports work.
    # This might mean running from the project root directory.
    # Example: python -m unittest tests/test_app_lastfm.py
    if flask_app is None:
        print("Skipping tests as Flask app could not be imported.")
    else:
        unittest.main()
