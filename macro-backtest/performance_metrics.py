"""Versioned unitized, contribution-adjusted investment performance.
No cash flows, holdings or trades are altered. Legacy metrics remain separate.
"""
import math
import numpy as np
import pandas as pd

CONVENTION = 'unitized_fee_inclusive_twr_v1'
CASHFLOW_TIMING = 'External contributions issue units at contemporaneous pre-flow NAV; trades and fees then change NAV; same-date event order preserved.'
ANNUALIZATION = 'Cumulative unit NAV annualized over actual inception-to-final-observation calendar days using 365.25; volatility and internal ratios use sqrt(12) monthly sampling.'

def checked_number(value, name, positive=False):
    if isinstance(value, bool) or not math.isfinite(float(value)) or (float(value) <= 0 if positive else float(value) < 0):
        raise ValueError('RUN INVALID — invalid '+name)
    return float(value)

def validate_capital(initial, fee, contribution=0):
    checked_number(initial,'initial capital',True)
    checked_number(contribution,'contribution (withdrawals unsupported)')
    if not 0 <= checked_number(fee,'fee') < 1:
        raise ValueError('RUN INVALID — fee must be below 100%')

class UnitizedPerformance:
    def __init__(self, initial, inception):
        self.units=checked_number(initial,'initial capital',True)
        self.inception=pd.Timestamp(inception).tz_localize(None)
        self.values={};self.wealth={};self.initial_nav=None
    def nav(self, value):
        return checked_number(value,'portfolio valuation',True)/self.units
    def initial(self,value):
        self.initial_nav=self.nav(value);self.observe(self.inception,value)
    def contribute(self,amount,pre_flow_value):
        amount=checked_number(amount,'contribution (withdrawals unsupported)')
        self.units+=amount/self.nav(pre_flow_value)
    def observe(self,date,value):
        d=pd.Timestamp(date).tz_localize(None)
        self.values[d]=self.nav(value);self.wealth[d]=float(value)
    def result(self,as_of=None):
        if self.initial_nav is None:raise ValueError('RUN INVALID — missing initial valuation')
        now=pd.Timestamp(as_of) if as_of is not None else pd.Timestamp.now(tz='UTC')
        now=now.tz_localize(None)
        # Never include a current partial calendar month. Actual observations,
        # not manufactured prices, supply endpoint values; coverage is a separate gate.
        cutoff=now.to_period('M').start_time
        nav=pd.Series(self.values,dtype=float).sort_index();nav=nav.loc[nav.index<cutoff]
        vals=pd.Series(self.wealth,dtype=float).sort_index()
        endpoints=[]
        for period,group in nav.groupby(nav.index.to_period('M')):
            observed=group.index[-1]
            if observed<=self.inception:continue
            endpoints.append((period.to_timestamp('M'),observed,float(group.iloc[-1])))
        if not endpoints:raise ValueError('RUN INVALID — no completed performance intervals')
        last_date=endpoints[-1][1];elapsed=(last_date-self.inception).days
        if elapsed<=0:raise ValueError('RUN INVALID — nonpositive performance duration')
        prior=1.;returns=[]
        for label,observed,value in endpoints:
            returns.append(value/prior-1);prior=value
        r=pd.Series(returns,dtype=float);sd=float(r.std());negative=r[r<0];down=float(negative.std());reasons={}
        def ratio(denom,key):
            if not math.isfinite(denom) or denom<=0:
                reasons[key]='Insufficient observations or zero sample deviation under internal monthly convention.';return None
            return float(r.mean()/denom*math.sqrt(12))
        sharpe=ratio(sd,'sharpe');sortino=ratio(down,'sortino')
        # Explicit unit baseline and inception fee ensure immediate losses count.
        path=np.array([1.,self.initial_nav]+[x[2] for x in endpoints]);dd=path/np.maximum.accumulate(path)-1
        vol=float(sd*math.sqrt(12)) if math.isfinite(sd) else None
        if vol is None:reasons['ann_vol']='Fewer than two sampled return intervals.'
        metrics={'ann_return':float(prior**(365.25/elapsed)-1),'ann_vol':vol,'sharpe':sharpe,'sortino':sortino,'max_drawdown':float(dd.min()),'worst_month':float(r.min()),'ending_value':float(vals.loc[last_date]),'months':len(returns),'undefined_reasons':reasons}
        return {'metric_convention':CONVENTION,'metrics':metrics,'initial_fee_return':float(self.initial_nav-1),'total_return':float(prior-1),'monthly_returns':[{'month_end':str(x[0].date()),'return':float(v)} for x,v in zip(endpoints,returns)],'cashflow_timing':CASHFLOW_TIMING,'annualization_basis':ANNUALIZATION,'inception_date':str(self.inception.date()),'final_observation_date':str(last_date.date()),'elapsed_days':elapsed,'first_period_partial':self.inception!=self.inception+pd.offsets.MonthEnd(0)}
