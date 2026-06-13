-- Industry-level market structure.
select
    coalesce(industry, 'Unclassified') as industry,
    count(*) as stock_count,
    round(sum(amount_100m), 2) as turnover_100m,
    round(avg(pct_chg), 2) as avg_return,
    round(avg(case when is_up then 1 else 0 end), 4) as up_ratio,
    sum(case when is_limit_up_proxy then 1 else 0 end) as limit_up_count
from analytics_market_daily
where trade_date = (select max(trade_date) from analytics_market_daily)
group by coalesce(industry, 'Unclassified')
order by turnover_100m desc;

-- Board-level turnover and return.
select
    coalesce(market, 'Unknown') as market,
    count(*) as stock_count,
    round(sum(amount_100m), 2) as turnover_100m,
    round(avg(pct_chg), 2) as avg_return
from analytics_market_daily
where trade_date = (select max(trade_date) from analytics_market_daily)
group by coalesce(market, 'Unknown')
order by turnover_100m desc;

-- Top daily movers.
select
    ts_code,
    name,
    industry,
    close,
    pct_chg,
    amount_100m
from analytics_market_daily
where trade_date = (select max(trade_date) from analytics_market_daily)
order by pct_chg desc
limit 30;
