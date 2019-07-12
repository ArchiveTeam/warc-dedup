import requests
import time


def get(url, status_codes=[200], content_length=0, max_tries=5,
        headers=None, cookies=None, preserve_url=False, stream=False,
        sleep_time=5, session=None, timeout=3600, fail_codes=[404, 403]):
    tries = 0
    while tries < max_tries:
        try:
            response = (session or requests).get(url, headers=headers,
                                                 cookies=cookies, stream=stream,
                                                 timeout=timeout)
            if not stream:
                assert len(response.text) > content_length
            if response.status_code in fail_codes:
                return False, response
            assert response.status_code in status_codes
            if preserve_url:
                assert response.url == url
            return True, response
        except:
            if tries < max_tries-1:
                time.sleep(sleep_time*1.3**tries)
            tries += 1
    return False, response

