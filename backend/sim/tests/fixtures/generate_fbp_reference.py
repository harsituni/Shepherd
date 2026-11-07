"""Independent 50-digit Decimal evaluation of published FBP equations.

No imports from the engine. Run manually to regenerate fbp_reference.json.
These are equation-verification fixtures, NOT empirical fire-growth validation.
"""
from decimal import Decimal as D, localcontext
import json
from pathlib import Path

SOURCES=[f'https://raw.githubusercontent.com/cffdrs/cffdrs_r/master/R/{f}.r'
         for f in ('initial_spread_index','rate_of_spread','back_rate_of_spread','buildup_effect','length_to_breadth')]


def expected(fuel,pc,ffmc,bui,wind):
    with localcontext() as ctx:
        ctx.prec=50
        pc,ffmc,bui,wind=map(lambda x:D(str(x)),(pc,ffmc,bui,wind))
        moisture=D('147.27723')*(101-ffmc)/(D('59.5')+ffmc)
        moisture_fn=D('91.9')*(-D('.1386')*moisture).exp()*(1+moisture**D('5.31')/D('4.93e7'))
        be=(50*D('.8').ln()*(1/bui-1/D(50))).exp()
        fw=(D('.05039')*wind).exp() if wind<=40 else 12*(1-(-D('.0818')*(wind-28)).exp())
        backward=(-D('.05039')*wind).exp()
        rates=[]
        for factor in (fw,backward):
            isi=D('.208')*factor*moisture_fn
            c=110*(1-(-D('.0282')*isi).exp())**D('1.5')
            d=30*(1-(-D('.0232')*isi).exp())**D('1.6')
            rates.append(be*(pc/100*c+(1-pc/100)*d*(1 if fuel=='M-1' else D('.2'))))
        lb=1+D('8.729')*(1-(-D('.030')*wind).exp())**D('2.155')
        return dict(zip(('ros','bros','fros','lb'),map(float,(*rates,sum(rates)/(2*lb),lb))))


if __name__=='__main__':
    inputs=[('M-1',50,92,90,0),('M-1',50,92,90,25),('M-1',50,92,90,60),
            ('M-2',25,95,50,25),('M-2',0,85,30,15),('M-1',100,101,50,0)]
    cases=[]
    for fuel,pc,ffmc,bui,wind in inputs:
        args=dict(fuel_type=fuel,pc=pc,ffmc=ffmc,bui=bui,ws_kmh=wind)
        cases.append({'input':args,'expected':expected(fuel,pc,ffmc,bui,wind)})
    out={'provenance':{'equations':'FCFDG 1992 ST-X-3: 26,27,45,46,53a,54,75,76,79; M-2 deciduous factor 0.2',
                       'sources':SOURCES,'method':'Independent 50-digit Decimal scalar evaluation; not engine-generated',
                       'coefficient':'FFMC coefficient 147.27723; positive-BUI cases only',
                       'limitation':'Equation verification only; no empirical calibration'},'cases':cases}
    Path(__file__).with_name('fbp_reference.json').write_text(json.dumps(out,indent=2)+'\n')
