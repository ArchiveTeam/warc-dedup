import datetime
import io


class Log:
    def __init__(self):
        self._log = []
        self._warcinfo_id = None

    def log(self, value: str):
        date = datetime.datetime.utcnow()
        for line in value.splitlines():
            line = line.strip()
            self._log.append((date, line))
            print(self._log[-1])

    def create_record(self, writer):
        payload = '\n'.join(['{} {}'.format(t.strftime('%Y-%m-%d %H:%M:%S.%f'),
                                            s)
                             for t, s in self._log])
        warc_headers = {
            'Content-Type': 'text/plain',
        }
        if self._warcinfo_id is not None:
            warc_headers['WARC-Warcinfo-ID'] = self._warcinfo_id
        return writer.create_warc_record(
            'urn:X-warc-dedup:log',
            'resource',
            warc_headers_dict=warc_headers,
            payload=io.BytesIO(payload.encode('utf8'))
        )

    def set_warcinfo(self, value: str):
        self._warcinfo_id = value

