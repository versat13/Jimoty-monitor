-- ジモティー監視ツール DBスキーマ (v1)
--
-- 根拠: 仕様書 v1.0 5章「データ管理方針（ローリング監視・非蓄積）」
--
-- 想定DB: SQLite (ローカル常駐ツールのため、外部DBサーバーを不要にする)
--
-- =====================================================================
-- 設計方針の要点 (基本方針の確認と、今回追加で決定した事項)
-- =====================================================================
--
-- 1. 「無期限に蓄積するデータベース」ではなく「今、一覧に出ている投稿を
--    映す監視バッファ」として設計する (仕様書5-1)。
--
-- 2. 一覧から消えた投稿の扱い (2026-08-23 追加決定事項):
--    仕様書5-1の原文は「一覧から消えた投稿は自動的に削除する」だが、
--    これをそのまま即時削除にすると、一覧の固定件数走査という制約上、
--    新着ラッシュで単に圏外に押し出されただけの投稿を、取引成立と
--    誤判定するリスクがある (このリスクは初回の設計相談時から指摘していた)。
--
--    検討の結果、以下の方式を採用する:
--        active  : 一覧に存在し、詳細も取得済みの通常状態
--        missing : 直近の巡回で一覧から見当たらなくなった状態(要確認)
--        (missing になった投稿は、次回巡回時に一覧を待たず個別ページへ
--         直接アクセスして確定判定する。是非は article_status_history
--         を参照。confirmed_closed または confirmed_deleted と判定
--         されたら物理削除、まだ生きていれば active に復帰させる)
--
--    「N回連続で圏外になったら削除」のような多段階カウンタ式の猶予
--    ロジックは採用しない。カウンタが増えるほど目視でのロジック検証が
--    難しくなり、意図しない不具合の温床になりやすいため
--    (ユーザーとの合意事項)。個別ページで直接確認する方式は、
--    新規投稿の詳細取得(フロー⑨⑩)と同じアクセスパターンを使い回せる
--    ため、実装上の特別扱いも少ない。
--
-- 3. 再浮上時の差分検知は仕様書通り「価格変化のみ」とする。
--    タイトル・説明文の変更は追跡しない (ユーザーとの合意事項、
--    2026-08-23)。将来的に必要になれば別途 title_history 等を追加する。
--
-- =====================================================================


-- ---------------------------------------------------------------------
-- 5-2. 永続テーブル（設定・ルール層、消さない）
-- ---------------------------------------------------------------------

-- NGワード (filters/keyword_filter.py の NgKeywordRule に対応)
-- タイトル＋一覧説明文の両方に適用 (仕様書5-2)
CREATE TABLE IF NOT EXISTS ng_keywords (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword     TEXT NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 1,  -- 0/1 (SQLiteにはBOOLEAN型がないため)
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ng_keywords_active ON ng_keywords(is_active);


-- NGカテゴリ (filters/category_filter.py の NgCategoryRule に対応)
-- NGカテゴリ (仕様書5-2, 6章)
-- category_idベース、一覧段階で判定可能 (仕様書5-2)
--
-- 実データ検証で判明した通り category_id は g-数字とは限らず、
-- スラッグ形式 (例: "oth") の場合もあるため TEXT型で保持する
-- (scraper/selectors/url_patterns.py の is_category_slug_url 参照)。
--
-- 2026-09-08追加: category_level列。ジモティーのカテゴリは
-- 「大カテゴリ (sale-XXXのURLスラッグ)」「ジャンル (g-数字)」
-- 「サブジャンル (g-数字、ジャンルのさらに配下)」の3階層があり、
-- 大カテゴリ・ジャンルを選んだ場合は配下すべてをNG扱いにしたい、
-- というユーザー要望に対応するため、登録時にどの階層かを記録する。
-- 'parent' (大カテゴリ) / 'mid' (ジャンル) / 'leaf' (サブジャンル、
-- または「ジャンルのみでサブジャンルの無い」投稿の唯一のカテゴリ)
-- の3値。判定ロジックは filters/category_filter.py 参照。
CREATE TABLE IF NOT EXISTS ng_categories (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id    TEXT NOT NULL,
    category_name  TEXT,  -- UI表示用の分かりやすい名前 (任意)
    category_level TEXT NOT NULL DEFAULT 'leaf',  -- 'parent'/'mid'/'leaf'
    is_active      INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ng_categories_active ON ng_categories(is_active);


-- NGユーザー／監視ユーザー (仕様書5-2, 5-4)
-- seller_idをキー、rule_typeで区別 (ng or watch)。
-- 表示フィルタのみで、取得自体は除外しない (仕様書5-4の絶対原則)。
--
-- 「監視ユーザー」(rule_type='watch') は 2026-08-24 に追加したウォッチ
-- リスト機能における「ユーザー監視」と統合された概念である。登録は
-- 出品者パネル(ユーザー個別UI)から行う想定 (ユーザーとの合意事項)。
-- ウォッチリスト対象は、NGワード/NGカテゴリ/NGユーザーの判定より
-- 優先して必ず表示する (合意事項: 「明示的に選んだものはノイズ除去の
-- 対象にしない」)。
CREATE TABLE IF NOT EXISTS seller_rules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id   TEXT NOT NULL UNIQUE,
    seller_name TEXT,  -- 登録時点の表示名 (変わる可能性があるので参考情報)
    rule_type   TEXT NOT NULL CHECK (rule_type IN ('ng', 'watch')),
    memo        TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_seller_rules_type ON seller_rules(rule_type, is_active);


-- watched_articles：投稿単位のウォッチリスト (2026-08-24 新設)
--
-- 「気軽に保存して気軽に消せる」もの (ユーザーの表現)。NGルールとは
-- 独立した機能であり、article_idが active_articles から削除された後も
-- watched_articles の行自体は残す (物理削除された投稿を「後で見返す」
-- ニーズより、ウォッチ解除の意思決定はユーザー自身が行うべきという判断。
-- article_id への外部キー制約はあえて付けない)。
--
-- 「問い合わせ終了したら一括で消せるボタン」(ユーザーの要望) は
-- API側で「全解除」エンドポイントとして提供する想定 (repository層では
-- 単純な全削除で足りるため、専用のカラムは持たせない)。
CREATE TABLE IF NOT EXISTS watched_articles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id  TEXT NOT NULL UNIQUE,
    memo        TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_watched_articles_article ON watched_articles(article_id);


-- 最終巡回時刻 (UI表示用、ロジック判断には使わない。仕様書5-2)
-- 巡回対象(都道府県+カテゴリ+市区町村の組み合わせ)ごとに1レコード
CREATE TABLE IF NOT EXISTS scan_state (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    prefecture          TEXT NOT NULL,
    category_slug       TEXT NOT NULL,
    category_id         TEXT,       -- NULL可 (カテゴリ指定なしの場合)
    area_id             TEXT,
    area_name           TEXT,
    last_scanned_at     TEXT,
    last_scan_item_count INTEGER,   -- 直近巡回で確認した件数 (UI参考表示用)

    -- 2026-09-07 追加: 地域指定方式・取得範囲設定
    --
    -- region_type: 監視対象の地域指定方式。公式サイトの仕様に合わせ、
    --   排他的な3種類のいずれか1つを選ぶ。
    --     'prefecture'      : 都道府県のみ (市区町村を絞らない)
    --     'prefecture_city' : 都道府県 + 市区町村
    --                         (既存の prefecture/area_id/area_name の
    --                         組み合わせがこれに相当。デフォルトかつ
    --                         これまでの唯一の方式なので、既存行は
    --                         全て 'prefecture_city' として扱う)
    --     'my_area'         : マイエリア (地図上の地点 + 半径)。
    --                         area_portal/{area_portal_id} 形式の
    --                         ページで、距離はPOSTフォーム
    --                         (distance_1/2/5/10/30) で選択される。
    --                         現時点ではHTML構造の調査 (2026-09-07
    --                         ユーザー提供サンプル) を終えた段階で、
    --                         一覧パーサーの対応・実際のスキャン
    --                         フローへの組み込みは未実装。列だけ
    --                         用意しておき、対応が入り次第
    --                         area_portal_id/distance_km を使う。
    region_type         TEXT NOT NULL DEFAULT 'prefecture_city'
                         CHECK (region_type IN ('prefecture', 'prefecture_city', 'my_area')),
    area_portal_id       TEXT,       -- my_area用: area_portal/{id} のid部分
    distance_km          INTEGER,    -- my_area用: 1/2/5/10/30 のいずれか (公式の選択肢)

    -- scan_range_mode: 1回の巡回で一覧を何ページ・何日分辿るか。
    --   'pages' (デフォルト): scan_range_value ページ目まで固定的に巡回する。
    --           デフォルト値は1 (=1ページ目のみ、これまでの挙動と同じ)。
    --   'days'  : 一覧を新しい順にページ送りしながら、各投稿の
    --           基準日 (更新日があれば更新日、なければ作成日) が
    --           「今日から scan_range_value 日より前」になった時点で
    --           打ち切る。一覧は新着順に並んでいる前提を利用する。
    -- pages/daysは排他 (同時に両方の上限を課す運用は現時点でしない)。
    scan_range_mode      TEXT NOT NULL DEFAULT 'pages'
                         CHECK (scan_range_mode IN ('pages', 'days')),
    scan_range_value     INTEGER NOT NULL DEFAULT 1,

    -- auto_scan_interval_minutes: 自動巡回の実行間隔 (分)。
    -- 2026-09-13変更: デフォルトを30分に設定 (ユーザーとの合意事項)。
    -- 新規インストール時は何も設定しなくても30分間隔の自動更新が
    -- 有効になる。NULLに戻せば「自動実行は無効・手動巡回のみ」の
    -- 状態にできる (設定画面から空欄で保存することで可能)。
    -- 既存DB (このデフォルト値導入前に作成されたもの) に対しては
    -- repository/article_repository.py のマイグレーション処理で
    -- 「まだ一度もこの値を保存したことがない場合のみ」30をセットする
    -- (ユーザーが既に意図的にNULL/別の値へ変更済みの場合は上書き
    -- しない。判定方法の詳細はマイグレーション処理のコメント参照)。
    auto_scan_interval_minutes INTEGER DEFAULT 30,

    -- 2026-09-10 追加: 巡回中の進捗表示用 (BottomNav付近のUI)。
    -- repository/article_repository.py の _SCAN_STATE_MIGRATION_COLUMNS
    -- と同じ理由・同じ意味を持つ列。詳細はそちらのコメント参照。
    scan_progress_current_page INTEGER,
    scan_progress_max_page     INTEGER,
    scan_progress_seen_count   INTEGER,

    -- 2026-09-11 追加: 保存期間削除の設定 (ユーザーとの合意事項)。
    -- 以前は「missing状態になってから21日固定」で自動削除していた
    -- (repository/article_repository.py の旧purge_expired_missing_
    -- articles参照)。これを、ユーザーが日数を自由に設定でき、かつ
    -- active(受付中)の投稿にも一律適用できる仕組みに一本化した。
    --
    -- 判定基準はarticle_statusに応じて自動的に使い分ける:
    --   article_status='active'  : 最終更新日 (updated_datetime。
    --                              無ければupdated_date_raw等は
    --                              MM/DD表記で年をまたぐ判定が
    --                              難しいため、last_seen_atを
    --                              フォールバックとして使う。
    --                              詳細はrepository/article_
    --                              retention_repository.py参照)
    --                              基準。値下げ等で更新されれば
    --                              保存期間が延長される。
    --   article_status='missing' : missing_since (一覧から消えた
    --                              巡回時刻) 基準。
    -- retention_enabledがFalseなら削除処理自体を行わない。
    retention_enabled          INTEGER NOT NULL DEFAULT 1,
    retention_days             INTEGER NOT NULL DEFAULT 7,

    -- 2026-09-15 追加: トースト通知・ブラウザ通知用 (通知設定の詳細は
    -- discord_notification_settings テーブルのコメント参照)。
    -- 直近の巡回で「検索」タブ (pickup_search) の条件にヒットした
    -- 新規投稿のarticle_idをJSON配列文字列として保存する
    -- (Discordへの通知試行対象と同じ集合)。自動更新 (サーバー側定期
    -- 実行) の巡回結果もここを経由してフロントから参照できるようにする。
    last_notified_article_ids TEXT,
    last_notified_at          TEXT,

    UNIQUE (prefecture, category_slug, category_id, area_id)
);


-- ---------------------------------------------------------------------
-- 出品者情報 (仕様書には明記の永続/バッファ区分がないが、
-- 複数投稿で同じ出品者を参照するため独立テーブルとする)
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sellers (
    seller_id           TEXT PRIMARY KEY,
    seller_name         TEXT,
    seller_profile_url  TEXT,
    gender              TEXT,
    post_count          INTEGER,
    rating              REAL,
    rating_count        INTEGER,
    identity_verified   INTEGER NOT NULL DEFAULT 0,
    phone_verified      INTEGER NOT NULL DEFAULT 0,
    description         TEXT,
    -- 追補仕様v1.1で発見した、プロフィールページ限定の追加情報
    -- (取得できた場合のみ埋める。詳細ページ経由だと取得できないためNULL許容)
    registration_date_raw TEXT,
    residential_area    TEXT,
    occupation          TEXT,
    rating_good         INTEGER,
    rating_normal       INTEGER,
    rating_bad          INTEGER,
    -- profile_fetched_at: プロフィールページ (/profiles/{seller_id}) を
    -- 一度でも取得したかどうかのマーカー (2026-08-30 新設)。
    -- NULLなら未取得 = 「続きを読む」で初回取得すべき状態。
    -- 「見るまでは取らない」設計 (遅延取得): 巡回時 (scheduler/job.py)
    -- ではこのカラムを一切更新しない。UIで出品者パネルを開いて
    -- 「続きを読む」または「更新」を押したときのみ、
    -- upsert_seller_profile() 経由でこの時刻が入る。
    profile_fetched_at  TEXT,
    first_seen_at       TEXT NOT NULL DEFAULT (datetime('now')),
    last_updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);


-- seller_other_articles：プロフィールページの投稿一覧のスナップショット
-- (2026-09-04 新設)。
--
-- 「この出品者の他の投稿」表示に、監視ツールが巡回で偶然検知した投稿
-- (active_articles由来) だけでなく、出品者の公式プロフィールページに
-- 載っている全投稿を反映したいというユーザー要望により追加。
--
-- active_articles とは別テーブルにした理由:
--   - プロフィールページの投稿一覧サマリ (ProfileArticleSummary) は
--     情報量が少なく (一覧的な要約のみ)、NGフィルタ判定・カテゴリ判定
--     など active_articles が前提とする巡回フロー (一覧→個別ページ→
--     フィルタ) を経由していない。無理に同じテーブルに混ぜると、
--     is_hidden_by_keyword等のフラグが常に未判定という中途半端な行が
--     生まれてしまうため、意図的に分離した。
--   - このテーブルの中身にNGフィルタ・is_watched等の機能は適用されない
--     (単純な一覧表示専用)。
--
-- 更新方法: 出品者のプロフィールページを取得する度 (fetch_seller_
-- profile_on_demand)、その出品者の行を全て削除してから作り直す
-- (洗い替え)。ジモティー側で投稿が削除された場合にも追従できるように
-- するため。
CREATE TABLE IF NOT EXISTS seller_other_articles (
    seller_id           TEXT NOT NULL,
    article_id          TEXT NOT NULL,
    url                 TEXT,
    listing_type        TEXT,  -- 「売ります」「あげます」等の区分
    title                TEXT,
    price               INTEGER,
    location            TEXT,
    description_short   TEXT,
    updated_date_raw    TEXT,  -- 「08/22」のようなMM/DD表記 (原文のまま保持)
    display_order       INTEGER NOT NULL,  -- プロフィールページ上の表示順
    fetched_at          TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (seller_id, article_id),
    FOREIGN KEY (seller_id) REFERENCES sellers(seller_id)
);

CREATE INDEX IF NOT EXISTS idx_seller_other_articles_seller
    ON seller_other_articles(seller_id, display_order);


-- ---------------------------------------------------------------------
-- 5-3. 監視バッファ層（ローリング）
-- ---------------------------------------------------------------------

-- active_articles：現在一覧に存在する投稿のスナップショット (仕様書5-3)
--
-- article_status の遷移については本ファイル冒頭のコメント参照:
--     active -> missing -> (active に復帰 | 削除)
CREATE TABLE IF NOT EXISTS active_articles (
    article_id          TEXT PRIMARY KEY,
    url                 TEXT NOT NULL,

    -- --- 一覧段階で取得できる情報 (ListArticle 由来) ---
    list_title           TEXT NOT NULL,
    price                INTEGER,
    prefecture           TEXT,
    area_id              TEXT,
    area_name            TEXT,
    station_id           TEXT,
    station_name         TEXT,
    category_id          TEXT,
    category_name        TEXT,
    tags                 TEXT,  -- JSON配列文字列として保存 (例: '["ELECOM","中古"]')
    description_short    TEXT,
    updated_date_raw      TEXT,
    created_date_raw      TEXT,
    favorite_count        INTEGER,
    thumbnail_url         TEXT,
    is_pr_slot            INTEGER NOT NULL DEFAULT 0,

    -- 2026-09-07 追加: タイトル変更の反映について。
    -- ジモティーの運用上「引取が決まりました！○○」「最終値下げ！○○」
    -- のように、既存投稿のタイトルが後から書き換えられることがある。
    -- 価格変更と異なりヒストリー(変遷)の記録は不要という合意のもと、
    -- list_title は毎回の巡回で単純に最新値へ上書きする
    -- (upsert_from_list_article参照。個別ページへの再アクセスは
    -- 発生させず、一覧のタイトル文字列の比較のみで行う)。
    -- title_changed_at は「直近いつタイトルが変わったか」をUI側で
    -- 軽く示せるようにするための補助列 (例: 小さな変更バッジ表示)。
    -- 変更履歴そのものは保持しない。
    title_changed_at      TEXT,

    -- 2026-09-10 追加: 価格変更の累計回数。
    -- repository/article_repository.py の _ACTIVE_ARTICLES_MIGRATION_COLUMNS
    -- と同じ理由・同じ意味を持つ列。詳細はそちらのコメント参照。
    price_change_count    INTEGER NOT NULL DEFAULT 0,

    -- --- 個別ページ取得後に埋まる情報 (DetailArticle 由来、フロー⑨⑩) ---
    full_title            TEXT,
    description_full      TEXT,
    category_mid_id       TEXT,
    category_mid_name     TEXT,
    category_parent_id    TEXT,
    category_parent_name  TEXT,
    city                  TEXT,
    ward                  TEXT,
    town                  TEXT,
    railway_line          TEXT,
    is_closed             INTEGER NOT NULL DEFAULT 0,  -- 「お問い合わせの受付は終了いたしました。」
    created_datetime      TEXT,  -- 詳細ページの「作成」表示 (時刻まで含む場合がある)
    updated_datetime      TEXT,  -- 詳細ページの「更新」表示

    seller_id             TEXT REFERENCES sellers(seller_id),

    -- --- フィルタ判定結果 (フロー⑦⑪、除外はせずフラグのみ。仕様書5-4) ---
    is_hidden_by_keyword  INTEGER NOT NULL DEFAULT 0,
    is_hidden_by_category INTEGER NOT NULL DEFAULT 0,
    is_hidden_by_seller_rule INTEGER NOT NULL DEFAULT 0,
    matched_ng_keywords   TEXT,  -- JSON配列文字列 (UI表示用、どのNGワードでヒットしたか)

    -- --- 監視バッファ管理用メタ情報 ---
    article_status        TEXT NOT NULL DEFAULT 'active'
                           CHECK (article_status IN ('active', 'missing')),
    missing_since          TEXT,  -- article_status='missing' になった巡回時刻

    -- 2026-09-11 追加: 「終了」タブの再設計 (ユーザーとの合意事項)。
    -- 以前はarticle_status='missing'になった投稿を一律「終了」扱い
    -- していたが、これには「本当に終了した投稿」と「取得範囲
    -- (ページ数/日数設定) からたまたま押し出されただけの投稿」が
    -- 区別なく混ざってしまう問題があった。
    --
    -- missing_kind は article_status='missing' の投稿を以下の3つに
    -- 細分類する:
    --   NULL                 : 未判定 (missingになった直後、まだ
    --                          confirmed_closed/range_uncertainの
    --                          いずれかに分類される前の一時的な状態。
    --                          通常は同じ巡回内で即座にどちらかに
    --                          分類されるため、UIから見えることは
    --                          ほぼ無いはず)
    --   'confirmed_closed'   : 「終了 (確定)」。今回の巡回で取得できた
    --                          投稿群のdisplay_order範囲の内側で消えた
    --                          ため (=本来なら見えるはずの順位に
    --                          いたのに見えなくなった)、自動で個別
    --                          ページに再アクセスして確認し、実際に
    --                          終了していたことが確定した投稿。
    --   'range_uncertain'    : 「監視範囲外」。今回の巡回で取得できた
    --                          投稿群のdisplay_order範囲の末尾より
    --                          後ろにいたため、取得範囲 (ページ数/
    --                          日数設定) の外に押し出されただけの
    --                          可能性がある投稿。自動での個別ページ
    --                          再アクセスは行わない (取得範囲を
    --                          広げれば自然に再度activeで拾えるか、
    --                          そのまま監視範囲外に留まり続けるかを
    --                          待つ)。
    -- 判定ロジックの詳細は scheduler/job.py の
    -- _classify_newly_missing_articles() docstring参照。
    missing_kind            TEXT
                             CHECK (missing_kind IS NULL
                                    OR missing_kind IN ('confirmed_closed', 'range_uncertain')),
    detail_fetched_at      TEXT,  -- 個別ページを取得した時刻 (未取得ならNULL)
    first_seen_at          TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at           TEXT NOT NULL DEFAULT (datetime('now')),  -- 直近、一覧に存在を確認できた時刻
    last_notified_at       TEXT,  -- トースト通知済みなら記録 (フロー⑬の重複通知防止)

    -- display_order: 直近の巡回で一覧に出現した順番 (2026-08-24 新設)。
    -- 「公式サイトと同じ並び順で見たい」というユーザー要望に対応するため、
    -- list_parser.parse_list_page() が返す配列順 (=一覧ページに実際に
    -- 表示されている順序、PR枠等の特殊ロジックも含めて) をそのまま
    -- 保持する。ソートの既定値としてこの列を使う想定
    -- (UI側のデフォルトソートキーを "display_order" にする)。
    -- 新規巡回のたびに 0, 1, 2... で振り直すため、値そのものに
    -- 意味はなく、あくまで「その巡回内での相対順序」を表す。
    display_order           INTEGER
);

CREATE INDEX IF NOT EXISTS idx_active_articles_status ON active_articles(article_status);
CREATE INDEX IF NOT EXISTS idx_active_articles_seller ON active_articles(seller_id);
CREATE INDEX IF NOT EXISTS idx_active_articles_category ON active_articles(category_id);


-- price_history：価格変化があった際の履歴 (article_idに紐づく。仕様書5-3)
--
-- 仕様書フロー⑧「既存：価格変化のみ確認、price_historyに追記」に対応。
-- タイトル・説明文の変更は追跡しない (2026-08-23 ユーザーとの合意事項)。
CREATE TABLE IF NOT EXISTS price_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id   TEXT NOT NULL REFERENCES active_articles(article_id) ON DELETE CASCADE,
    old_price    INTEGER,
    new_price    INTEGER,
    changed_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_price_history_article ON price_history(article_id);


-- article_status_history：ステータス変化の記録 (missing化・復帰・削除確定の追跡用)
--
-- 「猶予ロジックの複雑化を避けたい」というユーザーの懸念に対応するため、
-- カウンタ変数のような状態をコード内に持たず、
-- 「いつ、どのステータスに、なぜ変わったか」を都度レコードとして残す設計にした。
-- 目視での確認や、誤判定が起きた場合の後からの検証がしやすいことを優先している。
CREATE TABLE IF NOT EXISTS article_status_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id      TEXT NOT NULL,  -- 削除後も履歴として残すため外部キー制約は付けない
    from_status     TEXT,
    to_status       TEXT NOT NULL,
    reason          TEXT,  -- 例: "list_not_found" / "detail_confirmed_closed" / "detail_404" / "restored_still_active"
    occurred_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_article_status_history_article ON article_status_history(article_id);


-- ---------------------------------------------------------------------
-- 5-5. 検索ワードでピックアップするフィルタ (2026-09-08 新設)
--
-- 「フィルタ」タブや「NGワード」機能とは別物。NGワードは「一致したら
-- 隠す」フロー⑦の判定に使うのに対し、こちらは「一致したものだけを
-- 抽出・強調表示する」用途で、判定自体は巡回時ではなくクライアント
-- サイド (フロントエンド) で行う。このためDB側にはあくまで
-- 「検索条件そのもの」を保存するだけで、is_hidden_by_* のような
-- 判定結果フラグ列はこのテーブル群からは生まれない
-- (打ち合わせで合意した設計)。
-- ---------------------------------------------------------------------

-- pickup_search: 「検索」タブ用の恒常保存条件 (1件のみ、常に最新の
-- 条件で上書きする)。search_expression は最終的にフロントエンドの
-- 正規表現エンジンにそのまま渡す文字列。include_words/exclude_words
-- は正規表現ビルダー (含めたいワード/除外したいワードの入力欄) の
-- 入力内容をJSON配列文字列として保持し、次回開いたときにビルダーの
-- 入力欄を復元するために使う (search_expression自体は手直しされて
-- ビルダーの入力と食い違っている可能性があるため、両方を別々に持つ)。
CREATE TABLE IF NOT EXISTS pickup_search (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    search_expression   TEXT NOT NULL DEFAULT '',  -- 正規表現。空文字なら未設定(絞り込みなし)
    include_words_json  TEXT,  -- ビルダーの「含めたいワード」欄 (JSON配列文字列)
    exclude_words_json  TEXT,  -- ビルダーの「除外したいワード」欄 (JSON配列文字列)
    is_builder_synced    INTEGER NOT NULL DEFAULT 1,  -- 0/1。手直し後にビルダーとの同期が切れたか
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- search_history: 簡易フィルタ (既存タブ共通の一時的な検索) のワード
-- 履歴。検索条件自体は保存しない (都度リセット) が、打ち込んだ語句の
-- 履歴だけは残しておき、次回以降の入力候補として使う。
CREATE TABLE IF NOT EXISTS search_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    query       TEXT NOT NULL,
    searched_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_search_history_searched_at ON search_history(searched_at);

-- ---------------------------------------------------------------------
-- discord_notification_settings: 通知設定 (Discord / アプリ内トースト /
-- ブラウザ通知の共通テーブル、2026-09-13新設、2026-09-15拡張)
--
-- 「検索」タブ (pickup_search) の条件にヒットした新規投稿が見つかった
-- ときに通知する機能の設定。3種類の通知先 (Discord Webhook・アプリ内
-- トースト・ブラウザ通知) はいずれも同じ通知条件 (pickup_searchの
-- 正規表現にマッチ、かつNGでない新規投稿) を共有し、それぞれ個別に
-- 有効/無効を切り替えられる (「設定＞巡回設定＞通知」タブに統合、
-- 2026-09-15、ユーザーとの合意事項)。常に1件のみ保存する
-- (pickup_search・scan_stateと同じ設計方針)。テーブル名は既存の
-- discord_notification_settingsのまま維持している (Discord専用として
-- 設計されたテーブルにアプリ内・ブラウザ通知の列を後から追加した経緯を
-- 残すため。将来リネームする場合はマイグレーション方針を別途検討する)。
--
-- webhook_url: Discordのチャンネル設定「連携サービス」→「Webhookを
-- 作成」で発行されるURL (https://discord.com/api/webhooks/...)。
-- 空文字またはNULLなら「未設定・通知しない」として扱う。
--
-- enabled: Discord通知 (Webhook URLを設定済みのまま一時的に通知だけ
-- 止めたい場合のトグル。URLを消さずに済むようにするため)。
--
-- in_app_enabled: アプリ内トースト通知 (2026-09-15新設)。有効な場合、
-- ScanStatusContext がポーリングで新規の通知対象投稿を検知した際に
-- 画面内にトースト表示する (バックエンド側は対象投稿の算出のみを担い、
-- 実際の表示はフロントエンドが行う)。
--
-- browser_enabled: ブラウザ通知 (Web Notifications API、2026-09-15
-- 新設)。有効な場合、ブラウザの通知許可 (Notification.requestPermission)
-- が下りていればOS通知を発火する。タブを開いている間のみ動作する
-- (Service Worker等によるバックグラウンド配信は行わない設計、
-- ユーザーとの合意事項)。
--
-- 通知対象の判定 (「検索タブにヒットした新規投稿」) は3種類の通知先で
-- 共通。pickup_search.search_expression を正規表現として評価することで
-- 行う (filters/pickup_search_filter.py 参照。フロントエンド側の
-- frontend/src/utils/pickupSearch.js の matchesSearchExpression と
-- 同じロジックをPython側に移植したもの)。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS discord_notification_settings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    webhook_url    TEXT NOT NULL DEFAULT '',
    enabled        INTEGER NOT NULL DEFAULT 0,
    in_app_enabled INTEGER NOT NULL DEFAULT 0,
    browser_enabled INTEGER NOT NULL DEFAULT 0,
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------
-- deleted_articles_log: 保存期間切れで削除された投稿のスナップショット
-- (2026-09-14新設)
--
-- 経緯・設計思想 (ユーザーとの合意事項):
--     repository.article_repository.purge_expired_articles() が
--     保存期間切れの投稿をactive_articlesから物理削除する際、
--     「消えた投稿がどんな内容だったか、少しの間は見返せるように
--     したい」という要望から新設した。ただし「自分が明示的に消した
--     わけではない投稿にそこまで強い興味はない」ため、この履歴自体
--     にも保存期間を設け、期限が来たら履歴も一緒に削除してよい、
--     という方針になった (データ肥大化を避ける狙いもある)。
--
--     article_status_history (投稿削除以外にmissing化・復活等も
--     記録する監査ログ) とは目的が異なるため、あえて専用テーブルに
--     分離した。article_status_historyはarticle_idしか持たず、
--     投稿本体が消えた後にそれだけを見てもタイトル等が分からない
--     ため、一覧表示に使うにはこのテーブルのようにタイトル・価格等
--     のスナップショットを別途保持する必要がある。
--
-- 保存期間の考え方:
--     deleted_at基準で、active_articlesの保存期間 (scan_state.
--     retention_days) と同じ日数を過ぎたらこのテーブルからも削除する
--     (purge_expired_articles()の一環として、削除時に古いログの
--     掃除も行う。repository.article_repository参照)。
--
-- article_idへの外部キー制約は付けない (対象のactive_articlesの
-- 行は既に削除された後にこのテーブルへ書き込むため、そもそも参照
-- 先が存在しない)。
CREATE TABLE IF NOT EXISTS deleted_articles_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id          TEXT NOT NULL,
    url                 TEXT NOT NULL,
    list_title          TEXT NOT NULL,
    price               INTEGER,
    prefecture          TEXT,
    area_name           TEXT,
    category_name       TEXT,
    thumbnail_url       TEXT,
    article_status      TEXT NOT NULL,  -- 削除直前のステータス ('active' | 'missing')
    first_seen_at       TEXT,
    last_seen_at        TEXT,
    deleted_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_deleted_articles_log_deleted_at ON deleted_articles_log(deleted_at);

-- ---------------------------------------------------------------------
-- area_options: 都道府県ごとの市区町村候補キャッシュ (2026-09-12新設)
--
-- 設定画面「地域」タブで、都道府県を選ぶと市区町村がプルダウン選択式に
-- なる機能 (ユーザーとの合意事項)。以前は市区町村(area_id/area_name)を
-- 自由テキスト入力していたが、「一度公式から市区町村を取得する」
-- ボタンを押すと scraper.area_list_parser がジモティーの実際のページ
-- (https://jmty.jp/{prefecture}/sale) から市区町村一覧を取得し、
-- この表にキャッシュする。取得後は毎回ネットワークアクセスせず、
-- この表から選択肢を返す (再取得は明示的なボタン操作時のみ)。
--
-- 動的取得の仕組み自体は今回実装するが、都道府県ごとに1回はユーザーが
-- 「取得する」ボタンを押す必要がある (アプリ起動時に47都道府県分を
-- 自動取得することはしない。無駄なアクセスを避けるため)。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS area_options (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    prefecture    TEXT NOT NULL,   -- 都道府県スラッグ (例: "tokyo")
    area_id       TEXT NOT NULL,   -- 例: "999"
    area_name     TEXT NOT NULL,   -- ローマ字スラッグ (例: "shinjuku")
    display_name  TEXT NOT NULL,   -- 表示名 (例: "新宿区")
    display_order INTEGER NOT NULL,  -- ページ上での表示順 (プルダウンの並び順再現用)
    fetched_at    TEXT NOT NULL DEFAULT (datetime('now')),  -- この候補一覧を取得した巡回時刻

    UNIQUE (prefecture, area_id)
);

CREATE INDEX IF NOT EXISTS idx_area_options_prefecture ON area_options(prefecture, display_order);
