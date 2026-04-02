import {
  AreaChart as ReAreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend
} from 'recharts';

const brl = (v) => 'R$\u00a0' + Number(v).toLocaleString('pt-BR');

export function AreaChart({ data }) {
  const chartData = data.categories.map((label, i) => ({
    label,
    Receita: data.revenue[i],
    Lucro: data.profit[i]
  }));

  return (
    <div>
      <p className="text-xs font-bold uppercase tracking-widest text-gray-500 mb-3">
        Receita &amp; Lucro — Projeção
      </p>
      <ResponsiveContainer width="100%" height={200}>
        <ReAreaChart data={chartData}>
          <defs>
            <linearGradient id="gradReceita" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor="#38bdf8" stopOpacity={0.35} />
              <stop offset="95%" stopColor="#38bdf8" stopOpacity={0.02} />
            </linearGradient>
            <linearGradient id="gradLucro" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor="#4ade80" stopOpacity={0.28} />
              <stop offset="95%" stopColor="#4ade80" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#1f2a44" strokeDasharray="3 3" />
          <XAxis dataKey="label" tick={{ fill: '#475569', fontSize: 11 }} axisLine={false} tickLine={false} />
          <YAxis tickFormatter={brl} tick={{ fill: '#475569', fontSize: 10 }} axisLine={false} tickLine={false} width={80} />
          <Tooltip
            contentStyle={{ background: '#0d1020', border: '1px solid #1f2a44', borderRadius: 8 }}
            labelStyle={{ color: '#e2e8f0', fontWeight: 600 }}
            itemStyle={{ color: '#94a3b8' }}
            formatter={(v) => brl(v)}
          />
          <Legend wrapperStyle={{ fontSize: 11, color: '#64748b' }} />
          <Area type="monotone" dataKey="Receita" stroke="#38bdf8" strokeWidth={2.5} fill="url(#gradReceita)" dot={{ fill: '#38bdf8', r: 4 }} activeDot={{ r: 6 }} />
          <Area type="monotone" dataKey="Lucro"   stroke="#4ade80" strokeWidth={2.5} fill="url(#gradLucro)"   dot={{ fill: '#4ade80', r: 4 }} activeDot={{ r: 6 }} />
        </ReAreaChart>
      </ResponsiveContainer>
    </div>
  );
}
