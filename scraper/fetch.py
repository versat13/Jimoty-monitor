"""
ジモティーへのHTTPリクエストを担当するモジュール。

=== 実データ検証で判明した、仕様書からの重要な訂正 (2026-08-22) ===

仕様書 v1.0 4-1 では「地域・カテゴリ検索の方式」として
    POST https://jmty.jp/area_portal/search
    (distance・category_group_ids[]・authenticity_tokenを送信)
という、距離指定検索(エリアポータル)方式のみが記載されていた。

しかし実物調査の結果、今回検証に使った全ての一覧ページ
(例: https://jmty.jp/fukuoka/sale-pcp/g-1205/a-731-kitakyushu)
は、
    - 都道府県スラッグ (fukuoka)
    - カテゴリスラッグ (sale-pcp)
    - カテゴリID (g-1205、省略時はg-all)
    - 市区町村ID (a-731-kitakyushu)
を単純にURLパスへ連結した、CSRFトークン不要の単純GETリクエストで
取得できることが分かった。トップページ(https://jmty.jp/fukuoka)自体にも
CSRFトークンのmetaタグは存在するが、それを必要とするフォームは
「フリーワード検索」(GET, token不要)と「マイエリア設定」機能のみで、
本ツールが主目的とする「都道府県+カテゴリ+市区町村」の巡回には
area_portal/searchへのPOSTは不要と判断した。

このため本モジュールは、
    1. build_list_url()      : 固定URL方式 (メイン。CSRFトークン不要)
    2. fetch_area_portal()   : area_portal/search方式 (エリアポータルID
                                 を使った距離指定検索が必要な場合のオプション。
                                 仕様書通りCSRFトークンを都度取得してPOSTする)
の両方を用意し、通常の巡回は1.を使うことを推奨する設計とした。

=== アクセス方針 ===

個人の私的利用を前提とした低頻度アクセスとする (仕様書想定)。
- User-Agentは実ブラウザに準じたものを明示する
- 巡回間隔は呼び出し元 (scheduler/job.py) が制御する。本モジュールは
  単発のリクエスト関数のみを提供し、ループやスケジューリングは持たない
- リクエスト間に最低限のインターバルを空けるための sleep ヘルパーのみ提供する
"""

import time
from dataclasses import dataclass

import httpx

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

DEFAULT_TIMEOUT = 15.0

# 実データ検証 (2026-08-22) で確認したCSRFトークンのmeta要素名
CSRF_PARAM_META = "csrf-param"
CSRF_TOKEN_META = "csrf-token"


class FetchError(Exception):
    """HTTPリクエスト関連のエラー全般。"""


@dataclass
class CsrfToken:
    """フォーム送信前にGETで取得するCSRFトークン。"""

    param_name: str  # 通常 "authenticity_token"
    token_value: str


def build_client(user_agent: str = DEFAULT_USER_AGENT, timeout: float = DEFAULT_TIMEOUT) -> httpx.Client:
    """
    共通のhttpxクライアントを構築する。

    呼び出し元でコンテキストマネージャとして使うことを想定:
        with build_client() as client:
            html = fetch_list_page(client, url)
    """
    return httpx.Client(
        headers={"User-Agent": user_agent},
        timeout=timeout,
        follow_redirects=True,
    )


def build_list_url(
    prefecture: str,
    category_slug: str,
    *,
    category_id: str | None = None,
    area_id: str | None = None,
    area_name: str | None = None,
    page: int | None = None,
) -> str:
    """
    固定URL方式で一覧ページURLを組み立てる (実データ検証済みのメイン経路)。

    実データで確認した組み立てパターン:
        https://jmty.jp/{prefecture}/{category_slug}
        https://jmty.jp/{prefecture}/{category_slug}/g-{category_id}
        https://jmty.jp/{prefecture}/{category_slug}/a-{area_id}-{area_name}
        https://jmty.jp/{prefecture}/{category_slug}/g-{category_id}/a-{area_id}-{area_name}
        (2ページ目以降) 上記URL + "/p-2" 等

    2026-09-07 修正: 当初 "?p-2" (クエリパラメータ形式) としていたが、
    実データ (tests/fixtures/list_real.html の <link rel=next> 等、および
    ユーザーが実際に2ページ目をブラウザで開いて保存したHTMLの
    <link rel="canonical">) で確認したところ、正しくは "/p-2"
    (パスセグメント形式) だった。旧形式はジモティー側で認識されず、
    ?p-2 等を付けても常に1ページ目と同じ内容が返っていた
    (run_scan_with_range で複数ページ巡回しても実質1ページ目を
    繰り返し取得していた不具合の原因)。

    Args:
        prefecture: 都道府県スラッグ (例: "fukuoka")
        category_slug: カテゴリスラッグ (例: "sale-pcp")
        category_id: カテゴリID数字部分 (例: "1205")。Noneならカテゴリ指定なし
        area_id: 市区町村ID数字部分 (例: "731")。area_nameとセットで指定
        area_name: 市区町村名ローマ字 (例: "kitakyushu")
        page: ページ番号。2以上のときのみ "/p-N" を付与する

    Returns:
        組み立てたURL文字列
    """
    parts = [f"https://jmty.jp/{prefecture}/{category_slug}"]

    if category_id is not None:
        parts.append(f"g-{category_id}")

    if area_id is not None and area_name is not None:
        parts.append(f"a-{area_id}-{area_name}")

    url = "/".join(parts)

    if page is not None and page >= 2:
        url = f"{url}/p-{page}"

    return url


def fetch_html(client: httpx.Client, url: str) -> str:
    """
    指定URLをGETし、本文HTMLを返す。

    固定URL方式の一覧ページ・個別ページ・プロフィールページはいずれも
    このシンプルなGETで取得できることを実データで確認済み。
    """
    try:
        response = client.get(url)
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise FetchError(f"HTTPエラー: {e.response.status_code} url={url}") from e
    except httpx.RequestError as e:
        raise FetchError(f"リクエスト失敗: {e!r} url={url}") from e

    return response.text


def extract_csrf_token(html: str) -> CsrfToken | None:
    """
    ページHTMLからCSRFトークンを抽出する。

    実データ検証 (2026-08-22) で確認した形式:
        <meta name="csrf-param" content="authenticity_token"/>
        <meta name="csrf-token" content="ランダム文字列"/>
    一覧ページ・トップページの両方でこの形式を確認済み。
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")

    param_meta = soup.find("meta", attrs={"name": CSRF_PARAM_META})
    token_meta = soup.find("meta", attrs={"name": CSRF_TOKEN_META})

    if param_meta is None or token_meta is None:
        return None

    param_name = param_meta.get("content")
    token_value = token_meta.get("content")

    if not isinstance(param_name, str) or not isinstance(token_value, str):
        return None

    return CsrfToken(param_name=param_name, token_value=token_value)


def fetch_area_portal(
    client: httpx.Client,
    area_portal_id: str,
    *,
    distance: int,
    category_group_ids: list[int],
) -> str:
    """
    仕様書 v1.0 4-1 記載の distance指定検索 (area_portal/search) を実行する。

    固定URL方式 (build_list_url + fetch_html) で用が足りる場合は
    こちらを使う必要はない。エリアポータルIDを使った柔軟な距離指定
    (1/2/5/10/30km) が必要な場合のみのオプション経路として提供する。

    Args:
        client: build_client() で作成したhttpxクライアント
        area_portal_id: エリアポータルID (例: "1015117" = 熊谷周辺)
        distance: 距離 (km)。1/2/5/10/30のいずれか (仕様書の5段階固定)
        category_group_ids: カテゴリグループIDのリスト (例: [1] = 売ります)

    Returns:
        検索結果ページのHTML
    """
    if distance not in (1, 2, 5, 10, 30):
        raise ValueError(f"distanceは1/2/5/10/30のいずれかである必要があります: {distance}")

    portal_url = f"https://jmty.jp/area_portal/{area_portal_id}"
    portal_html = fetch_html(client, portal_url)

    csrf = extract_csrf_token(portal_html)
    if csrf is None:
        raise FetchError(f"CSRFトークンが取得できませんでした: {portal_url}")

    form_data = {
        csrf.param_name: csrf.token_value,
        "distance": str(distance),
    }
    # category_group_ids[] は複数値になりうるため、httpxのdataでは
    # 同名キーのリストとして渡す
    data_items = list(form_data.items()) + [
        ("category_group_ids[]", str(cid)) for cid in category_group_ids
    ]

    try:
        response = client.post("https://jmty.jp/area_portal/search", data=data_items)
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise FetchError(f"HTTPエラー: {e.response.status_code} url=area_portal/search") from e
    except httpx.RequestError as e:
        raise FetchError(f"リクエスト失敗: {e!r} url=area_portal/search") from e

    return response.text


def polite_sleep(seconds: float) -> None:
    """
    リクエスト間の待機。scheduler側から明示的に呼び出す想定。

    具体的な巡回間隔の値そのものは本モジュールでは決め打ちしない
    (仕様書に「低頻度アクセス」とあるのみで具体的な秒数の記載がないため。
    README「未検証・保留中の項目」参照。scheduler/job.py 実装時に
    利用規約を踏まえて確定させる)。
    """
    time.sleep(seconds)
