create table if not exists dim_stock (
    ts_code varchar,
    symbol varchar,
    name varchar,
    area varchar,
    industry varchar,
    market varchar,
    list_date date
);

create table if not exists analytics_market_daily (
    ts_code varchar,
    trade_date date,
    open double,
    high double,
    low double,
    close double,
    pre_close double,
    change double,
    pct_chg double,
    vol double,
    amount double,
    symbol varchar,
    name varchar,
    area varchar,
    industry varchar,
    market varchar,
    list_date date,
    amount_100m double,
    vol_100m_shares double,
    amplitude double,
    is_up boolean,
    is_limit_up_proxy boolean,
    is_limit_down_proxy boolean,
    net_mf_amount_100m double
);
