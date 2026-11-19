"""Real exchange-calendar integration with synthetic prices; no market downloads."""
import importlib.util
from pathlib import Path
import unittest
import pandas as pd
import exchange_calendars as xc
from exchange_calendars.errors import DateOutOfBounds
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('calendar_runtime',HERE/'acceptance_runtime.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)

class CalendarBoundaries(unittest.TestCase):
 def frame(self,dates):return pd.DataFrame({'Close':[100.]*len(dates)},index=pd.to_datetime(dates))
 def check(self,label,observed):
  result=r.price_coverage(self.frame([observed]),['SYNTHETIC'],[label],'2026-10-25T00:00:00Z','synthetic-input')
  self.assertEqual(result['months'][0]['expected_last_session'],observed)
  self.assertEqual(result['months'][0]['last_observation'],observed)
  self.assertEqual(result['months'][0]['month_end'],label)
 def test_sunday_month_start_march_failure_regression(self):self.check('2026-03-31','2026-03-31')
 def test_holiday_month_start_and_weekend_end(self):self.check('2026-01-31','2026-01-30')
 def test_sunday_month_end(self):self.check('2026-05-31','2026-05-29')
 def test_holiday_month_end(self):self.check('2021-05-31','2021-05-28')
 def test_business_boundaries(self):self.check('2026-09-30','2026-09-30')
 def test_multiple_months_each_terminal_session_verified(self):
  result=r.price_coverage(self.frame(['2026-03-31','2026-04-30','2026-05-29']),['SYNTHETIC'],['2026-03-31','2026-04-30','2026-05-31'],'2026-10-25T00:00:00Z','synthetic-input')
  self.assertEqual([x['expected_last_session'] for x in result['months']],['2026-03-31','2026-04-30','2026-05-29'])
 def test_stale_final_session_still_rejected(self):
  with self.assertRaisesRegex(ValueError,'stale/incomplete'):
   r.price_coverage(self.frame(['2026-03-30']),['SYNTHETIC'],['2026-03-31'],'2026-10-25T00:00:00Z','synthetic-input')
 def test_missing_month_still_rejected(self):
  with self.assertRaisesRegex(ValueError,'empty raw month'):
   r.price_coverage(self.frame(['2026-02-27']),['SYNTHETIC'],['2026-03-31'],'2026-10-25T00:00:00Z','synthetic-input')
 def test_missing_one_ticker_terminal_session_rejected(self):
  raw=pd.DataFrame({('AAA','Close'):[100.,101.],('BBB','Close'):[100.,float('nan')]},index=pd.to_datetime(['2026-03-30','2026-03-31']))
  with self.assertRaisesRegex(ValueError,'stale/incomplete'):
   r.price_coverage(raw,['AAA','BBB'],['2026-03-31'],'2026-10-25T00:00:00Z','synthetic-input')
 def test_supplied_calendar_cannot_clamp_missing_end(self):
  narrow=xc.get_calendar('XNYS',start='2026-02-01',end='2026-03-30')
  with self.assertRaises(DateOutOfBounds):
   r.price_coverage(self.frame(['2026-03-30']),['SYNTHETIC'],['2026-03-31'],'2026-10-25T00:00:00Z','synthetic-input',narrow)
if __name__=='__main__':unittest.main(verbosity=2)
