-- Market breadth trend.
select
    trade_date,
    count(*) as stock_count,
    round(sum(amount_100m), 2) as turnover_100m,
    round(avg(pct_chg), 2) as avg_return,
    round(avg(case when is_up then 1 else 0 end), 4) as up_ratio,
    sum(case when is_limit_up_proxy then 1 else 0 end) as limit_up_count
from analytics_market_daily
group by trade_date
order by trade_date;

-- Industry rotation by recent average return.
select
    industry,
    count(*) as observations,
    round(avg(pct_chg), 2) as avg_return,
    round(sum(amount_100m), 2) as turnover_100m
from analytics_market_daily
where trade_date >= (
    select max(trade_date) - interval 20 day
    from analytics_market_daily
)
group by industry
order by avg_return desc nulls last;

