import sys

from warc_dedup import deduplicate


def main():
    if len(sys.argv) == 1:
        raise Exception('Please provide the WARC file as argument.')
    deduplicate.Warc(*sys.argv[1:]).deduplicate()

if __name__ == '__main__':
    main()

