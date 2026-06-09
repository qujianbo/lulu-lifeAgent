from app.services.briefing.rss import parse_rss_articles, split_rss_urls


def test_parse_rss_articles() -> None:
    xml = """
    <rss><channel>
      <item><title>第一条资讯</title><link>https://example.com/1</link></item>
      <item><title>第二条资讯</title><link>https://example.com/2</link></item>
    </channel></rss>
    """

    articles = parse_rss_articles(xml, source="https://example.com/rss")

    assert len(articles) == 2
    assert articles[0].title == "第一条资讯"
    assert articles[0].link == "https://example.com/1"


def test_split_rss_urls() -> None:
    assert split_rss_urls("https://a.test/rss, https://b.test/rss") == [
        "https://a.test/rss",
        "https://b.test/rss",
    ]
