-- Latest-day high volatility stocks using SQL window functions.
with risk_base as (
    select
        ts_code,
        name,
        industry,
        trade_date,
        pct_chg,
        amount_100m,
        stddev(pct_chg) over (
            partition by ts_code
            order by trade_date
            rows between 19 preceding and current row
        ) as vol_20d
    from analytics_market_daily
)
select *
from risk_base
where trade_date = (select max(trade_date) from analytics_market_daily)
order by vol_20d desc nulls last
limit 50;

-- Abnormal turnover expansion.
with turnover_z as (
    select
        ts_code,
        name,
        industry,
        trade_date,
        amount_100m,
        avg(amount_100m) over (
            partition by ts_code
            order by trade_date
            rows between 19 preceding and current row
        ) as avg_amount_20d,
        stddev(amount_100m) over (
            partition by ts_code
            order by trade_date
            rows between 19 preceding and current row
        ) as std_amount_20d
    from analytics_market_daily
)
select
    *,
    (amount_100m - avg_amount_20d) / nullif(std_amount_20d, 0) as amount_zscore
from turnover_z
where trade_date = (select max(trade_date) from analytics_market_daily)
order by amount_zscore desc nulls last
limit 50;

