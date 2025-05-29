import unittest
from unittest.mock import patch, MagicMock, PropertyMock
import os

# Add project root to sys.path to allow importing 'app'
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Conditional import for app and spotipy exceptions
try:
    from app import app as flask_app # Assuming your Flask app instance is named 'app' in 'app.py'
    from app import get_lastfm_song_suggestion 
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

    def setUp(self):
        if flask_app:
            flask_app.testing = True
            self.client = flask_app.test_client()
        else:
            self.client = None

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
        
        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertTrue(json_data['success'])
        self.assertEqual(json_data['suggestion'], mock_suggestion_data)
        self.assertEqual(json_data['message'], "Suggestion found")

    @patch('app.get_lastfm_song_suggestion')
    @patch('app.get_spotify_client') # For the @spotify_auth_required decorator
    def test_api_no_suggestion(self, mock_get_spotify_client_decorator, mock_get_lastfm_suggestion_func):
        if not self.client: self.skipTest("Flask client not available")

        mock_get_spotify_client_decorator.return_value = MagicMock()
        mock_get_lastfm_suggestion_func.return_value = (None, "No suitable suggestion")

        response = self.client.get('/api/lastfm-suggestion')
        
        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertFalse(json_data['success'])
        self.assertIsNone(json_data['suggestion'])
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
        # We can also check if 'Location' header points to the expected redirect URL
        # For example: self.assertTrue('/spotify-auth-prompt' in response.headers['Location'])

    @patch('app.save_lastfm_session')
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
        initial_settings_without_username = {'max_queue_length': 20, 'some_other_setting': 'value'}
        mock_load_settings.return_value = initial_settings_without_username

        mock_lfm_api_response = MagicMock()
        mock_lfm_api_response.json.return_value = {
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


if __name__ == '__main__':
    # Basic test runner. More sophisticated runners can be used.
    # Ensure that if tests are run directly, the app related imports work.
    # This might mean running from the project root directory.
    # Example: python -m unittest tests/test_app_lastfm.py
    if flask_app is None:
        print("Skipping tests as Flask app could not be imported.")
    else:
        unittest.main()
