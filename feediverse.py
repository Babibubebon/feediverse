#!/usr/bin/env python3

import os
import re
import sys
import yaml
import argparse
import dateutil
import feedparser
import logging
import time

from bs4 import BeautifulSoup
from mastodon import Mastodon
from mastodon.Mastodon import MastodonError
from datetime import datetime, timezone, MINYEAR
from pprint import pprint

DEFAULT_CONFIG_FILE = os.path.join("~", ".feediverse")

logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--dry-run", action="store_true",
                        help=("perform a trial run with no changes made: "
                              "don't toot, don't save config"))
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="be verbose")
    parser.add_argument("-c", "--config",
                        help="config file to use",
                        default=os.path.expanduser(DEFAULT_CONFIG_FILE))
    parser.add_argument("-s", "--sleep", type=float, default=0.0)

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    config_file = args.config

    logger.debug(f"using config file: {config_file}")
    logger.debug(f"sleep interval: {args.sleep} s")

    if not os.path.isfile(config_file):
        setup(config_file)

    config = read_config(config_file)

    masto = Mastodon(
        api_base_url=config['url'],
        access_token=config['access_token']
    )

    has_error = False
    newest_post = config['updated']
    for feed in config['feeds']:
        if args.verbose:
            logger.debug(f"fetching {feed['url']} entries since {config['updated']}")
        for entry in get_feed(feed['url'], config['updated']):
            logger.debug(entry)
            newest_post = max(newest_post, entry['updated'])

            status = {
                'status': feed['template'].format(**entry)[:config.get('max_chars', 500)],
                'visibility': config.get('visibility')
            }
            if args.dry_run:
                pprint(status)
                continue
            try:
                res = masto.status_post(**status)
            except MastodonError:
                logging.exception("failed to post a status")
                has_error = True
                break
            logger.debug(res)

            time.sleep(args.sleep)

    if not args.dry_run:
        config['updated'] = newest_post.isoformat()
        save_config(config, config_file)

    sys.exit(1 if has_error else 0)


def get_feed(feed_url, last_update):
    feed = feedparser.parse(feed_url)
    if last_update:
        entries = [e for e in feed.entries
                   if dateutil.parser.parse(e['updated']) > last_update]
    else:
        entries = feed.entries
    entries.sort(key=lambda e: e.updated_parsed)
    for entry in entries:
        yield get_entry(entry)


def get_entry(entry):
    hashtags = []
    for tag in entry.get('tags', []):
        t = tag['term'].replace(' ', '_').replace('.', '').replace('-', '')
        hashtags.append('#{}'.format(t))
    summary = entry.get('summary', '')
    content = entry.get('content', '') or ''
    if content:
        content = cleanup(content[0].get('value', ''))
    url = entry.id if hasattr(entry, 'id') else entry.link
    return {
        'url': url,
        'link': entry.link,
        'title': cleanup(entry.title),
        'summary': cleanup(summary),
        'content': content,
        'hashtags': ' '.join(hashtags),
        'updated': dateutil.parser.parse(entry['updated'])
    }


def cleanup(text):
    html = BeautifulSoup(text, 'html.parser')
    text = html.get_text()
    text = re.sub('\xa0+', ' ', text)
    text = re.sub('  +', ' ', text)
    text = re.sub(' +\n', '\n', text)
    text = re.sub('\n\n\n+', '\n\n', text, flags=re.M)
    return text.strip()


def yes_no(question):
    res = input(question + ' [y/n] ')
    return res.lower() in "y1"


def save_config(config, config_file):
    copy = dict(config)
    with open(config_file, 'w') as fh:
        fh.write(yaml.dump(copy, default_flow_style=False, allow_unicode=True))


def read_config(config_file):
    config = {
        'updated': datetime(MINYEAR, 1, 1, 0, 0, 0, 0, timezone.utc)
    }
    with open(config_file) as fh:
        cfg = yaml.load(fh, yaml.SafeLoader)
        if 'updated' in cfg:
            cfg['updated'] = dateutil.parser.parse(cfg['updated'])
    config.update(cfg)
    return config


def setup(config_file):
    url = input('What is your Mastodon Instance URL?: ')
    have_app = yes_no('Do you have your app credentials already?')
    if have_app:
        name = input('app name (e.g. feediverse): ')
        client_id = input('What is your app\'s client id: ')
        client_secret = input('What is your client secret: ')
    else:
        print("Ok, I'll need a few things in order to get your access token")
        name = input('app name (e.g. feediverse): ')
        client_id, client_secret = Mastodon.create_app(
            api_base_url=url,
            client_name=name,
            scopes=['read', 'write'],
            website='https://github.com/Babibubebon/feediverse'
        )

    # authorize and get access token
    m = Mastodon(client_id=client_id, client_secret=client_secret, api_base_url=url)
    auth_request_url = m.auth_request_url(client_id=client_id)
    print('Open the following URL and login:', auth_request_url)
    code = input('Paste displayed code: ')
    access_token = m.log_in(code=code, scopes=['read', 'write'])

    feed_url = input('RSS/Atom feed URL to watch: ')
    old_posts = yes_no('Shall already existing entries be posted, too?')
    config = {
        'name': name,
        'url': url,
        'client_id': client_id,
        'client_secret': client_secret,
        'access_token': access_token,
        'feeds': [
            {'url': feed_url, 'template': "{title}\n{link}"}
        ],
        'visibility': 'unlisted',
        'max_chars': 500
    }
    if not old_posts:
        config['updated'] = datetime.now(tz=timezone.utc).isoformat()
    save_config(config, config_file)

    print("")
    print("Your feediverse configuration has been saved to {}".format(os.path.realpath(config_file)))
    print("Add a line line this to your crontab to check every 15 minutes:")
    print(f"*/15 * * * * {sys.argv[0]}")
    print("")


if __name__ == "__main__":
    main()
