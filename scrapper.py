"""
Scrapper implementation
"""
import random
from datetime import datetime
import json
import pathlib
import re
import shutil
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import requests

from constants import ASSETS_PATH, CRAWLER_CONFIG_PATH, DOMAIN_URL, ROOT_URL, RUSSIAN_ROOT_URL
from core_utils.article import Article
from core_utils.pdf_utils import PDFRawFile


class IncorrectURLError(Exception):
    """
    Seed URL does not match standard pattern
    """


class NumberOfArticlesOutOfRangeError(Exception):
    """
    Total number of articles to parse is too big
    """


class IncorrectNumberOfArticlesError(Exception):
    """
    Total number of articles to parse in not integer
    """


class HTMLParser:
    """
    Parser implementation
    """

    def __init__(self, article_url, article_id):
        """
        Init
        """
        self.article_url = article_url
        self.article_id = article_id
        self.article = Article(url=article_url, article_id=article_id)

    def parse(self):
        """
        Parses the URL
        """
        time.sleep(random.uniform(0.0, 1.0))

        response = requests.get(self.article_url)
        article_bs = BeautifulSoup(response.text, 'html.parser')

        self._fill_article_with_text(article_bs)
        self._fill_article_with_meta_information(article_bs)

        return self.article

    def _fill_article_with_text(self, article_bs):
        """
        Fills self.article with text from article_bs
        """
        download_table_data_bs = article_bs.find('strong', string=" Загрузить статью")
        download_table_row_bs = download_table_data_bs.parent.parent.parent

        pdf_url_bs = download_table_row_bs.find('a')

        pdf_raw_file = PDFRawFile(pdf_url_bs['href'], self.article_id)

        pdf_raw_file.download()
        text = pdf_raw_file.get_text()

        parts_of_article = text.split('Список литературы')

        self.article.text = ''.join(parts_of_article[:-1])

    def _fill_article_with_meta_information(self, article_bs):
        """
        Fills self.article with meta information
        """

        self.article.title = article_bs.find('h3').get_text()

        td_authors = article_bs.find('td', string='Авторы')
        table_bs = td_authors.parent.parent
        table_row_bs = table_bs.find('tr', {"class": 'unnrow'})
        first_author_bs = table_row_bs.find('a')

        self.article.author = first_author_bs.text

        text_date = re.search(r'Поступила в редакцию\s+\d{2}\.\d{2}\.\d{4}', self.article.text)
        date_re = re.search(r'\d{2}\.\d{2}\.\d{4}', text_date.group(0))

        self.article.date = datetime.strptime(date_re.group(0), '%d.%m.%Y')


class Crawler:
    """
    Crawler implementation
    """

    def __init__(self, seed_urls, max_articles: int):
        self._seed_urls = seed_urls
        self.max_articles = max_articles
        self.urls = []

    def _extract_url(self, article_bs):
        """
        Finds urls from the given article_bs
        """
        table_rows_bs = article_bs.find_all('tr', {"class": "unnrow"})

        urls = []
        overall_urls_count = len(self.urls)

        links_bs = []

        for table_row_bs in table_rows_bs:
            links_bs.extend(table_row_bs.find_all('a'))

        for link_bs in links_bs:
            if overall_urls_count + 1 > self.max_articles:
                break

            # Checks if the link leads to an article
            match = re.match(r'^\?anum', link_bs['href'])

            if not match:
                continue

            link_url = ''.join([DOMAIN_URL, link_bs['href']])

            if link_url not in self.urls and link_url not in urls:
                urls.append(link_url)
                overall_urls_count += 1

        return urls

    def find_articles(self):
        """
        Finds articles
        """
        for seed_url in self._seed_urls:
            if len(self.urls) + 1 > self.max_articles:
                break

            time.sleep(random.uniform(0.0, 1.0))

            response = requests.get(seed_url)
            article_bs = BeautifulSoup(response.text, features="html.parser")

            self.urls.extend(self._extract_url(article_bs))

    def get_search_urls(self):
        """
        Returns seed_urls param
        """
        return self._seed_urls


class CrawlerRecursive(Crawler):
    """
    CrawlerRecursive implementation
    """
    def __init__(self, seed_urls, max_articles: int):
        self.crawled_urls = []

        super().__init__(seed_urls, max_articles)

    def find_articles(self):
        """
        Finds articles
        """
        start_url = self._seed_urls[0]
        self._seed_urls = []

        self.urls = load_scrapped_urls()
        pre_scrapped_url_count = len(self.urls)

        self.crawl(start_url)
        self.urls = self.urls[pre_scrapped_url_count:]

    def crawl(self, url_to_crawl):
        if len(self.urls) + 1 > self.max_articles:
            return

        time.sleep(random.uniform(0.0, 1.0))

        response = requests.get(url_to_crawl)
        response_bs = BeautifulSoup(response.text, features="html.parser")
        links_bs = response_bs.find_all('a')

        for link_bs in links_bs:
            try:
                link = link_bs['href']
            except KeyError:
                continue

            if not link:
                continue

            match = re.match(r'(^http://|^https://)', link)

            if not match:
                link = urljoin(url_to_crawl, link)

            if not absolute_url_structure_is_valid(link):
                continue

            # Ignore english version to avoid duplicates
            if RUSSIAN_ROOT_URL not in link or 'eng' in link:
                continue

            if link in self.crawled_urls:
                continue

            self.crawled_urls.append(link)
            match = re.search(r'\?jnum=', link)

            if match:
                self._seed_urls.append(link)

                response = requests.get(link)
                article_bs = BeautifulSoup(response.text, features="html.parser")

                self.urls.extend(self._extract_url(article_bs))

                if len(self.urls) + 1 > self.max_articles:
                    break
            else:
                # Recursion
                self.crawl(link)


def prepare_environment(base_path):
    """
    Creates ASSETS_PATH folder if not created and removes existing folder
    """
    path = pathlib.Path(base_path)

    if path.exists():
        shutil.rmtree(path)

    path.mkdir(parents=True)


def should_reset_crawler(crawler_path):
    with open(crawler_path, 'r') as crawler_file:
        crawler_config = json.load(crawler_file)

        if 'reset_parser' not in crawler_config:
            return True

        return crawler_config['reset_parser']


def validate_config(crawler_path):
    """
    Validates given config
    """
    with open(crawler_path, 'r') as crawler_file:
        crawler_config = json.load(crawler_file)

    if 'total_articles_to_find_and_parse' not in crawler_config:
        raise IncorrectNumberOfArticlesError

    if 'seed_urls' not in crawler_config:
        raise IncorrectURLError

    max_articles = crawler_config['total_articles_to_find_and_parse']

    if not isinstance(max_articles, int):
        raise IncorrectNumberOfArticlesError

    if max_articles <= 0:
        raise IncorrectNumberOfArticlesError

    if max_articles > 100:
        raise NumberOfArticlesOutOfRangeError

    seed_urls = crawler_config['seed_urls']

    if not isinstance(seed_urls, list) or not seed_urls:
        raise IncorrectURLError

    for seed_url in seed_urls:
        if not absolute_url_structure_is_valid(seed_url):
            raise IncorrectURLError

    return seed_urls, max_articles


def absolute_url_structure_is_valid(url_to_check):
    match = re.match(r'(^http://|^https://)', url_to_check)

    if not match or ROOT_URL not in url_to_check:
        return False

    return True


def load_scrapped_urls():
    scrapped_urls = []

    pathlib_assets_path = pathlib.Path(ASSETS_PATH)

    if not pathlib_assets_path.exists():
        return []

    for file_name in pathlib_assets_path.iterdir():
        if file_name.suffix == '.json':
            with open(file_name, encoding='utf-8') as file:
                config = json.load(file)

            stem = file_name.stem
            number = stem[0]

            pdf_path = ASSETS_PATH / f'{number}_raw.pdf'

            if pdf_path.is_file():
                scrapped_urls.append(config['url'])

    return scrapped_urls


if __name__ == '__main__':
    outer_seed_urls, outer_max_articles = validate_config(CRAWLER_CONFIG_PATH)

    if should_reset_crawler(CRAWLER_CONFIG_PATH) or not pathlib.Path(ASSETS_PATH).exists():
        prepare_environment(ASSETS_PATH)

    pre_scrapped_urls = load_scrapped_urls()

    crawler = CrawlerRecursive(outer_seed_urls, outer_max_articles)
    crawler.find_articles()

    for i, url in enumerate(crawler.urls):
        parser = HTMLParser(url, i + len(pre_scrapped_urls) + 1)
        article = parser.parse()
        article.save_raw()
