import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from 'recharts';

const COLORS = ['#7c3aed', '#38bdf8', '#4ade80'];

export function DonutChart({ data }) {
  return (
    <div>
      <p className="text-xs font-bold uppercase tracking-widest text-gray-500 mb-3">
        Origem do Tráfego
      </p>
      <ResponsiveContainer width="100%" height={200}>
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            innerRadius={55}
            outerRadius={75}
            paddingAngle={4}
            dataKey="value"
          >
            {data.map((_, i) => (
              <Cell key={i} fill={COLORS[i % COLORS.length]} opacity={0.85} />
            ))}
          </Pie>
          <Tooltip
            contentStyle={{ background: '#0d1020', border: '1px solid #1f2a44', borderRadius: 8 }}
            itemStyle={{ color: '#94a3b8' }}
            formatter={(v) => `${v}%`}
          />
          <Legend wrapperStyle={{ fontSize: 11, color: '#64748b' }} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
