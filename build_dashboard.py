"""
Constructor del dashboard HTML interactivo con los hallazgos mas impactantes del EDA.
Salida: dashboard_EDA.html (autocontenido, se abre en cualquier navegador).
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import plotly.io as pio

# =========================================================================
# Carga (usa los limpios que ya genero el notebook)
# =========================================================================
cli = pd.read_csv('clientes_limpio.csv')
cat = pd.read_csv('catalogo_limpio.csv')
his = pd.read_csv('historial_limpio.csv')
his['fecha'] = pd.to_datetime(his['fecha'])
his['mes']   = his['fecha'].dt.to_period('M').astype(str)

# Paleta Movistar
COL = {
    'azul'   : '#0091EA',
    'azul_o' : '#00B0FF',
    'verde'  : '#4CAF50',
    'rojo'   : '#F44336',
    'naranja': '#FF6D00',
    'gris'   : '#B0BEC5',
    'morado' : '#8E44AD',
}

# =========================================================================
# KPIs
# =========================================================================
n_clientes   = len(cli)
n_ofrecim    = len(his)
n_elig_mt    = int(cli['elegible_mt'].sum())
n_ya_mt      = int(cli['es_movistar_total'].sum())
tasa_acept   = (his['resultado']=='aceptada').mean()
tasa_rech    = (his['resultado']=='rechazada').mean()
tasa_pend    = (his['resultado']=='pendiente').mean()
tasa_cont    = (his['contactabilidad']=='contactado').mean()
motivo_top   = (his[his['resultado']=='rechazada']['motivo_rechazo']
                  .value_counts(normalize=True).iloc[0] * 100)
arpu_prom    = cli['monto_facturado_prom'].mean()

# =========================================================================
# FIGURAS
# =========================================================================

# --- Fig 1: donut del target
fig1 = go.Figure(go.Pie(
    labels=['Aceptada','Rechazada','Pendiente'],
    values=[(his['resultado']=='aceptada').sum(),
            (his['resultado']=='rechazada').sum(),
            (his['resultado']=='pendiente').sum()],
    hole=.6, marker_colors=[COL['verde'], COL['rojo'], COL['gris']],
    textinfo='label+percent', textfont_size=14))
fig1.update_layout(title='Distribucion del target (resultado)', height=380,
                   margin=dict(t=50,b=10,l=10,r=10),
                   annotations=[dict(text=f'{n_ofrecim:,}<br>ofrecim.',
                                     x=0.5, y=0.5, font_size=16, showarrow=False)])

# --- Fig 2: motivos de rechazo
motivos = (his[his['resultado']=='rechazada']['motivo_rechazo']
              .value_counts(normalize=True) * 100).sort_values()
fig2 = go.Figure(go.Bar(
    x=motivos.values, y=motivos.index, orientation='h',
    marker_color=[COL['rojo'] if v==motivos.max() else COL['naranja'] for v in motivos.values],
    text=[f'{v:.1f}%' for v in motivos.values], textposition='outside'))
fig2.update_layout(title='Por que rechazan los clientes? (motivos de rechazo)',
                   xaxis_title='% del total de rechazos', height=380,
                   margin=dict(t=50,b=40,l=110,r=40))

# --- Fig 3: aceptacion por canal
acept_canal = (his.assign(a=(his['resultado']=='aceptada').astype(int))
                  .groupby('canal')['a'].mean().sort_values(ascending=False) * 100)
fig3 = go.Figure(go.Bar(
    x=acept_canal.index, y=acept_canal.values,
    marker_color=COL['azul'],
    text=[f'{v:.1f}%' for v in acept_canal.values], textposition='outside'))
fig3.update_layout(title='Tasa de aceptacion por canal',
                   yaxis_title='% aceptacion', xaxis_title='',
                   height=380, margin=dict(t=50,b=40,l=40,r=40))

# --- Fig 4: aceptacion por tipo de oferta
acept_tipo = (his.assign(a=(his['resultado']=='aceptada').astype(int))
                 .groupby('tipo_oferta')['a'].mean().sort_values() * 100)
colores_tipo = [COL['verde'] if 'movistar_total' in t else COL['azul_o'] for t in acept_tipo.index]
fig4 = go.Figure(go.Bar(
    x=acept_tipo.values, y=acept_tipo.index, orientation='h',
    marker_color=colores_tipo,
    text=[f'{v:.1f}%' for v in acept_tipo.values], textposition='outside'))
fig4.update_layout(title='Tasa de aceptacion por tipo de oferta',
                   xaxis_title='% aceptacion', height=380,
                   margin=dict(t=50,b=40,l=130,r=40))

# --- Fig 5: evolucion mensual
por_mes = (his.assign(a=(his['resultado']=='aceptada').astype(int))
              .groupby('mes').agg(ofrec=('ofrecimiento_id','count'),
                                   tasa=('a','mean')))
fig5 = make_subplots(specs=[[{'secondary_y': True}]])
fig5.add_trace(go.Bar(x=por_mes.index, y=por_mes['ofrec'],
                      name='# ofrecimientos', marker_color=COL['gris'], opacity=0.7),
               secondary_y=False)
fig5.add_trace(go.Scatter(x=por_mes.index, y=por_mes['tasa']*100,
                          name='Tasa aceptacion (%)', mode='lines+markers',
                          line=dict(color=COL['naranja'], width=3),
                          marker=dict(size=10)),
               secondary_y=True)
fig5.update_layout(title='Volumen y tasa de aceptacion por mes',
                   height=380, margin=dict(t=50,b=40,l=40,r=40),
                   legend=dict(orientation='h', y=1.15))
fig5.update_yaxes(title_text='# ofrecimientos', secondary_y=False)
fig5.update_yaxes(title_text='% aceptacion',   secondary_y=True)

# --- Fig 6: perfil geografico
geo = cli['ubicacion_departamento'].value_counts()
fig6 = go.Figure(go.Bar(
    x=geo.values, y=geo.index, orientation='h',
    marker_color=COL['azul'],
    text=[f'{v:,}' for v in geo.values], textposition='outside'))
fig6.update_layout(title='Distribucion geografica de clientes',
                   xaxis_title='# clientes', height=430,
                   margin=dict(t=50,b=40,l=110,r=60))

# --- Fig 7: distribucion facturacion por segmento MT
cli['segmento_mt'] = np.select(
    [cli['es_movistar_total'], cli['elegible_mt']],
    ['Ya tiene MT', 'Elegible MT'], default='Base general')
fig7 = go.Figure()
for seg, color in [('Base general', COL['gris']),
                   ('Elegible MT', COL['naranja']),
                   ('Ya tiene MT', COL['azul_o'])]:
    fig7.add_trace(go.Box(y=cli.loc[cli['segmento_mt']==seg, 'monto_facturado_prom'],
                          name=seg, marker_color=color, boxmean=True))
fig7.update_layout(title='Facturacion (S/) segun relacion con Movistar Total',
                   yaxis_title='S/ facturados / mes', height=430,
                   margin=dict(t=50,b=40,l=40,r=40), showlegend=False)

# --- Fig 8: heatmap canal x tipo_oferta -> tasa de aceptacion
pivot = (his.assign(a=(his['resultado']=='aceptada').astype(int))
            .pivot_table(index='tipo_oferta', columns='canal', values='a', aggfunc='mean') * 100)
fig8 = go.Figure(go.Heatmap(
    z=pivot.values, x=pivot.columns, y=pivot.index,
    colorscale='RdYlGn', zmid=pivot.values.mean(),
    text=[[f'{v:.1f}%' for v in row] for row in pivot.values],
    texttemplate='%{text}', textfont={'size':12},
    colorbar=dict(title='% acept')))
fig8.update_layout(title='Tasa de aceptacion: canal x tipo de oferta',
                   height=430, margin=dict(t=50,b=40,l=110,r=40))

# --- Fig 9: correlacion features numericas
num_cols = ['antiguedad_meses','monto_facturado_prom','consumo_datos_gb_prom',
            'consumo_voz_min_prom','dias_mora_prom','n_reclamos','n_actividad_canal',
            'tasa_aceptacion']
corr = cli[num_cols].corr()
fig9 = go.Figure(go.Heatmap(
    z=corr.values, x=corr.columns, y=corr.index,
    colorscale='RdBu_r', zmid=0, zmin=-1, zmax=1,
    text=[[f'{v:.2f}' for v in row] for row in corr.values],
    texttemplate='%{text}', textfont={'size':11},
    colorbar=dict(title='r')))
fig9.update_layout(title='Correlacion entre features numericas (Pearson)',
                   height=520, margin=dict(t=50,b=100,l=140,r=40))

# --- Fig 10: histograma monto_facturado con marcadores de segmento
fig10 = go.Figure()
for seg, color in [('Base general', COL['gris']),
                   ('Elegible MT', COL['naranja']),
                   ('Ya tiene MT', COL['azul_o'])]:
    fig10.add_trace(go.Histogram(x=cli.loc[cli['segmento_mt']==seg, 'monto_facturado_prom'],
                                 name=seg, marker_color=color, opacity=0.7,
                                 nbinsx=50))
fig10.update_layout(title='Distribucion de facturacion mensual por segmento',
                    xaxis_title='S/ / mes', yaxis_title='# clientes',
                    barmode='overlay', height=430,
                    margin=dict(t=50,b=40,l=40,r=40))

# =========================================================================
# HTML
# =========================================================================
def to_div(fig):
    return pio.to_html(fig, include_plotlyjs=False, full_html=False,
                       config={'displayModeBar': False})

html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Dashboard EDA - Desafio 02 Movistar</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, sans-serif; }}
body {{ background: #f4f6fa; color: #1a2332; }}
.header {{ background: linear-gradient(135deg, #0091EA 0%, #00B0FF 100%);
           color: white; padding: 28px 40px; box-shadow: 0 2px 8px rgba(0,0,0,.1); }}
.header h1 {{ font-size: 26px; font-weight: 600; margin-bottom: 4px; }}
.header .subtitle {{ font-size: 15px; opacity: 0.92; }}
.container {{ padding: 28px 40px; max-width: 1600px; margin: auto; }}
.kpi-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 16px; margin-bottom: 24px; }}
.kpi {{ background: white; padding: 20px; border-radius: 10px;
        box-shadow: 0 2px 6px rgba(0,0,0,.06); border-left: 4px solid #0091EA; }}
.kpi .label {{ font-size: 12px; text-transform: uppercase; color: #667;
               letter-spacing: 0.5px; margin-bottom: 6px; }}
.kpi .value {{ font-size: 26px; font-weight: 700; color: #0091EA; }}
.kpi .sub {{ font-size: 11px; color: #99a; margin-top: 4px; }}
.kpi.warn {{ border-left-color: #FF6D00; }} .kpi.warn .value {{ color: #FF6D00; }}
.kpi.ok   {{ border-left-color: #4CAF50; }} .kpi.ok .value   {{ color: #4CAF50; }}
.kpi.bad  {{ border-left-color: #F44336; }} .kpi.bad .value  {{ color: #F44336; }}
.grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px; margin-bottom: 20px; }}
.grid-full {{ grid-column: 1 / -1; }}
.card {{ background: white; padding: 16px; border-radius: 10px;
         box-shadow: 0 2px 6px rgba(0,0,0,.06); }}
.section-title {{ font-size: 18px; font-weight: 600; color: #1a2332;
                  margin: 26px 0 14px; padding-bottom: 8px;
                  border-bottom: 2px solid #0091EA; }}
.insights {{ background: #FFF8E1; border-left: 4px solid #FFA000; padding: 16px 20px;
             border-radius: 8px; margin-bottom: 20px; }}
.insights h3 {{ color: #E65100; margin-bottom: 10px; font-size: 15px; }}
.insights ul {{ margin-left: 20px; line-height: 1.8; font-size: 14px; }}
.insights strong {{ color: #BF360C; }}
.footer {{ text-align: center; padding: 20px; color: #99a; font-size: 12px;
           border-top: 1px solid #ddd; margin-top: 20px; }}
@media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>

<div class="header">
  <h1>Dashboard EDA - Personalizacion Comercial Inteligente</h1>
  <div class="subtitle">Desafio 02 - Hackathon AI Telecom 2026 (Movistar) &middot; Analisis de {n_clientes:,} clientes y {n_ofrecim:,} ofrecimientos (ene-jun 2026)</div>
</div>

<div class="container">

  <div class="section-title">Indicadores clave</div>
  <div class="kpi-row">
    <div class="kpi"><div class="label">Clientes analizados</div><div class="value">{n_clientes:,}</div><div class="sub">base sintetica anonimizada</div></div>
    <div class="kpi warn"><div class="label">Elegibles MT</div><div class="value">{n_elig_mt:,}</div><div class="sub">{n_elig_mt/n_clientes*100:.1f}% - target prioritario</div></div>
    <div class="kpi ok"><div class="label">Ya tienen MT</div><div class="value">{n_ya_mt:,}</div><div class="sub">{n_ya_mt/n_clientes*100:.1f}% de la base</div></div>
    <div class="kpi"><div class="label">ARPU promedio</div><div class="value">S/ {arpu_prom:.1f}</div><div class="sub">facturacion mensual</div></div>
    <div class="kpi ok"><div class="label">Tasa aceptacion</div><div class="value">{tasa_acept*100:.1f}%</div><div class="sub">de ofrecimientos totales</div></div>
    <div class="kpi bad"><div class="label">Tasa rechazo</div><div class="value">{tasa_rech*100:.1f}%</div><div class="sub">principal motivo: precio ({motivo_top:.0f}%)</div></div>
    <div class="kpi"><div class="label">Contactabilidad</div><div class="value">{tasa_cont*100:.1f}%</div><div class="sub">campanias entregadas</div></div>
  </div>

  <div class="insights">
    <h3>Hallazgos clave del EDA</h3>
    <ul>
      <li><strong>Precio</strong> explica el <strong>{motivo_top:.1f}%</strong> de los rechazos - la contraoferta (rebate) debe atacar precio, no cambiar producto.</li>
      <li><strong>13,650 clientes elegibles a Movistar Total</strong> no lo tienen - segmento con mayor potencial de conversion.</li>
      <li>Los canales <strong>Tienda y Call Out</strong> muestran mayor tasa de aceptacion; Digital domina en volumen pero convierte menos.</li>
      <li><strong>Movistar Total</strong> como tipo de oferta tiene la mejor tasa de aceptacion en el historial - hay demanda latente.</li>
      <li>La distribucion mensual es estable (~50k ofrec/mes) - <strong>no es problema de forecasting</strong>, pero requiere split temporal para evitar leakage.</li>
      <li><strong>Correlacion 0.99</strong> entre monto_facturado_prom y monto_facturado_prom_6m: redundantes, conservar solo una.</li>
      <li>Lima concentra el <strong>45% de la base</strong> - validar metricas por region para evitar overfitting territorial.</li>
    </ul>
  </div>

  <div class="section-title">Comportamiento del target</div>
  <div class="grid">
    <div class="card">{to_div(fig1)}</div>
    <div class="card">{to_div(fig2)}</div>
  </div>

  <div class="section-title">Efectividad por canal y tipo de oferta</div>
  <div class="grid">
    <div class="card">{to_div(fig3)}</div>
    <div class="card">{to_div(fig4)}</div>
    <div class="card grid-full">{to_div(fig8)}</div>
  </div>

  <div class="section-title">Perfil del cliente y segmentacion MT</div>
  <div class="grid">
    <div class="card">{to_div(fig6)}</div>
    <div class="card">{to_div(fig7)}</div>
    <div class="card grid-full">{to_div(fig10)}</div>
  </div>

  <div class="section-title">Dinamica temporal y correlaciones</div>
  <div class="grid">
    <div class="card">{to_div(fig5)}</div>
    <div class="card">{to_div(fig9)}</div>
  </div>

  <div class="footer">
    Dashboard generado a partir del notebook <code>EDA_Data_Wrangling.ipynb</code> &middot;
    Fuente: dataset sintetico Hackathon AI Telecom 2026 - Desafio 02
  </div>

</div>
</body>
</html>
"""

with open('dashboard_EDA.html', 'w', encoding='utf-8') as f:
    f.write(html)

print('Dashboard creado: dashboard_EDA.html')
print(f'  Tamano: {len(html)//1024} KB')
