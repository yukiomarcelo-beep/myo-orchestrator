import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer,
} from 'recharts';

const brl = (v) => 'R$ ' + Number(v).toLocaleString('pt-BR', { maximumFractionDigits: 0 });

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-[#0a0e27] border border-white/10 rounded-xl px-3 py-2 text-[11px] shadow-xl">
      <p className="font-semibold text-gray-300 mb-1.5">{label}</p>
      {payload.map(p => (
        <div key={p.dataKey} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: p.color }} />
          <span className="text-gray-500">{p.name}:</span>
          <span className="font-semibold" style={{ color: p.color }}>{brl(p.value)}</span>
        </div>
      ))}
    </div>
  );
}

export function PLChart({ data }) {
  if (!data?.length) return (
    <div className="flex items-center justify-center h-48 text-[11px] text-gray-700">
      Sem histórico disponível
    </div>
  );

  return (
    <ResponsiveContainer width="100%" height={200}>
      <ComposedChart data={data} margin={{ top: 4, right: 4, left: -10, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
        <XAxis
          dataKey="mes"
          tick={{ fill: '#4b5563', fontSize: 10 }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          tickFormatter={v => 'R$' + (v >= 1000 ? (v / 1000).toFixed(0) + 'k' : v)}
          tick={{ fill: '#4b5563', fontSize: 10 }}
          axisLine={false}
          tickLine={false}
          width={42}
        />
        <Tooltip content={<CustomTooltip />} />
        <Legend
          wrapperStyle={{ fontSize: '10px', paddingTop: '8px' }}
          formatter={(v) => <span style={{ color: '#6b7280' }}>{v}</span>}
        />
        <Bar dataKey="receita" name="Receita" fill="rgba(139,92,246,0.5)" radius={[3, 3, 0, 0]} maxBarSize={28} />
        <Bar dataKey="custo"   name="Custo"   fill="rgba(239,68,68,0.3)"  radius={[3, 3, 0, 0]} maxBarSize={28} />
        <Line
          type="monotone"
          dataKey="lucro"
          name="Lucro"
          stroke="#10b981"
          strokeWidth={2}
          dot={{ fill: '#10b981', r: 3, strokeWidth: 0 }}
          activeDot={{ r: 4 }}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
