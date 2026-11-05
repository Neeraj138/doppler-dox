import csv
import io
import json
import threading
import unittest
import urllib.request
import urllib.error
import numpy as np
from scipy.optimize import brentq
from scipy.io import wavfile
from doppler_dox.physics import flyby, fit_flyby, ecef
from doppler_dox.audio import decode, RATE, Spectrogram
from doppler_dox.tracks import load_tracks, timestamp, Elevations
from doppler_dox.demo import make_demo, EPOCH, TRUTH
from doppler_dox.search import run_search
from doppler_dox.server import make_server


class PhysicsTests(unittest.TestCase):
    def test_retarded_model_against_independent_root_solve(self):
        speed, distance, c, f0, cpa = 110., 2300., 343., 140., 80.
        times = np.linspace(30, 140, 31)
        expected = []
        for t in times:
            receive = t-cpa+distance/c
            te = brentq(lambda s: s+np.hypot(distance,speed*s)/c-receive, -500, 500)
            expected.append(f0/(1+speed*speed*te/np.hypot(distance,speed*te)/c))
        np.testing.assert_allclose(flyby(times,f0,speed,distance,cpa),expected,atol=1e-9)
        self.assertAlmostEqual(float(flyby([cpa],f0,speed,distance,cpa)[0]),f0)
        self.assertGreater(expected[0], expected[-1])

    def test_fit_recovers_parameters_with_noise(self):
        t = np.linspace(10, 130, 150)
        f = flyby(t,130,95,2200,70)+np.random.default_rng(3).normal(0,.06,len(t))
        result = fit_flyby(np.column_stack((t,f)))
        self.assertAlmostEqual(result['speed_mps'],95,delta=.5)
        self.assertAlmostEqual(result['distance_m'],2200,delta=20)
        self.assertAlmostEqual(result['cpa_s'],70,delta=.1)

    def test_bad_trace_and_sound_speed_rejected(self):
        for points in ([], [[1,2]]*10, [[i,float('nan')] for i in range(10)]):
            with self.assertRaises(ValueError): fit_flyby(points)
        with self.assertRaises(ValueError): fit_flyby([[i,100-i] for i in range(10)],100)

    def test_wgs84_equator(self):
        np.testing.assert_allclose(ecef(0,0), [6378137,0,0], atol=1e-6)


class TrackTests(unittest.TestCase):
    def test_units_duplicates_unknown_and_jets(self):
        header='track_id,time,latitude,longitude,altitude_m,engine\n'
        text=header
        for name,engine in [('PROP','T'),('UNKNOWN',''),('JET','J')]:
            for i in range(3): text+=f'{name},{i*5},40,{-75+i*.001},1000,{engine}\n'
        tracks,stats=load_tracks(text)
        self.assertEqual(stats['excluded_jets'],1)
        self.assertEqual({t.id for t in tracks},{'PROP','UNKNOWN'})
        with self.assertRaises(ValueError): load_tracks(text+'PROP,0,40,-75,1000,T\n')
        with self.assertRaises(ValueError): timestamp('2026-11-01T00:00:00')
        self.assertEqual(timestamp('2026-11-01T00:00:00Z'),EPOCH)

    def test_terrain_coverage(self):
        terrain=Elevations('latitude,longitude,elevation_m\n40,-75,90\n')
        self.assertEqual(terrain.at(40,-75),90)
        with self.assertRaises(ValueError): terrain.at(41,-75)

    def test_coverage_gap_is_not_interpolated(self):
        text='track_id,time,latitude,longitude,altitude_m\n'
        for i in [0,5,10,200,205,210]:text+=f'A,{i},40,{-75+i*.0001},1000\n'
        tracks,_=load_tracks(text)
        self.assertEqual(len(tracks),2)


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.demo=make_demo()

    def test_spectrogram_ridge_to_fit(self):
        d=self.demo
        for event in d['events']:
            p=np.asarray(event['points'])
            traced=d['spec'].trace(float(p[:,0].min()),float(p[:,0].max()),float(p[:,1].min()-5),float(p[:,1].max()+5))
            fitted=fit_flyby(traced)
            self.assertAlmostEqual(fitted['speed_mps']/event['speed_mps'],1,delta=.07)
            self.assertAlmostEqual(fitted['distance_m']/event['distance_m'],1,delta=.12)
            self.assertLess(fitted['rms_hz'],.4)

    def test_two_events_recover_truth_trace_and_brightness(self):
        d=self.demo
        for mode in ('trace','brightness'):
            result=run_search(d['spec'],d['tracks'],d['events'],dict(d['config'],score_mode=mode))
            best=result['candidates'][0]
            error=np.linalg.norm(ecef(best['latitude'],best['longitude'])-ecef(*TRUTH))
            self.assertLess(error,100,mode)
            self.assertAlmostEqual(best['recording_start_epoch'],EPOCH,delta=1)
            self.assertEqual(best['tracks'],['DEMO-PROP-01','DEMO-PROP-02'])
            self.assertEqual(len(best['event_scores']),2)

    def test_single_event_requires_time_and_retains_ambiguity_warning(self):
        d=self.demo
        config=dict(d['config'],score_mode='trace')
        with self.assertRaises(ValueError):run_search(d['spec'],d['tracks'],d['events'][:1],config)
        config['recording_start']=EPOCH
        result=run_search(d['spec'],d['tracks'],d['events'][:1],config)
        self.assertTrue(result['candidates'])
        self.assertTrue(any('mirror' in w for w in result['warnings']))

    def test_inconsistent_event_spacing_has_no_candidate(self):
        d=self.demo
        corrupt=dict(d['events'][1],cpa_s=d['events'][1]['cpa_s']+40)
        result=run_search(d['spec'],d['tracks'],[d['events'][0],corrupt],dict(d['config'],offset_tolerance_s=.5))
        self.assertFalse(result['candidates'])

    def test_search_budget_is_enforced(self):
        d=self.demo
        with self.assertRaises(ValueError):
            run_search(d['spec'],d['tracks'],d['events'],dict(d['config'],north=41,south=40,west=-75,east=-74,spacing_m=50))

    def test_wav_decode_and_short_file_rejection(self):
        buf=io.BytesIO();wavfile.write(buf,RATE,np.zeros(10*RATE,dtype=np.int16))
        decoded=decode(buf.getvalue());self.assertEqual(len(decoded),10*RATE)
        with self.assertRaises(ValueError):decode(b'not audio')


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=make_server(port=0)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.base=f'http://127.0.0.1:{cls.server.server_port}'
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()

    def request(self,path,data=None,token=None):
        headers={}
        if token:headers['X-Workbench-Token']=token
        request=urllib.request.Request(self.base+path,data=json.dumps(data).encode() if data is not None else None,headers=headers)
        return urllib.request.urlopen(request,timeout=30)

    def test_ui_assets_and_local_request_protection(self):
        for path in ('/','/app.js','/style.css'):
            with self.request(path) as response:self.assertEqual(response.status,200)
        with self.request('/api/state') as response:token=json.load(response)['token']
        with self.assertRaises(urllib.error.HTTPError) as caught:self.request('/api/demo',{})
        self.assertEqual(caught.exception.code,403)
        request=urllib.request.Request(self.base+'/api/demo',data=b'{}',headers={'X-Workbench-Token':token,'Origin':'https://example.com'})
        with self.assertRaises(urllib.error.HTTPError) as caught:urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code,403)
        with self.assertRaises(urllib.error.HTTPError) as caught:self.request('/api/tracks',{},token)
        self.assertEqual(caught.exception.code,400)

    def test_demo_fit_and_search_input_validation(self):
        with self.request('/api/state') as response:token=json.load(response)['token']
        with self.request('/api/demo',{},token) as response:demo=json.load(response)
        self.assertEqual(len(demo['events']),2)
        with self.request('/api/view?start=20&end=90&low=50&high=200') as response:view=json.load(response)
        self.assertGreater(view['width'],2)
        with self.request('/api/track-map') as response:self.assertEqual(len(json.load(response)['tracks']),2)
        with self.assertRaises(urllib.error.HTTPError) as caught:self.request('/api/events',{'events':[{}]},token)
        self.assertEqual(caught.exception.code,400)
