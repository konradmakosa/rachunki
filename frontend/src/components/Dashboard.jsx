import { useState, useEffect, useMemo } from 'react'
import { fetchChartData } from '../api'
import { Zap, Flame, Droplets, TrendingUp, TrendingDown, Minus, Filter, Calendar, ChevronLeft, ChevronRight } from 'lucide-react'
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, ComposedChart, Area, AreaChart
} from 'recharts'

const PROVIDER_CONFIG = {
  eon:   { color: '#eab308', fill: 'rgba(234,179,8,0.15)',  label: 'e.on (prąd)',  icon: Zap,      unit: 'kWh' },
  pgnig: { color: '#f97316', fill: 'rgba(249,115,22,0.15)', label: 'PGNiG (gaz)',   icon: Flame,    unit: 'kWh' },
  mpwik: { color: '#3b82f6', fill: 'rgba(59,130,246,0.15)', label: 'MPWiK (woda)',  icon: Droplets, unit: 'm³' },
}

const LOCATIONS = [
  { value: '', label: 'Wszystkie lokalizacje' },
  { value: 'Płatnicza', label: 'Płatnicza 65' },
  { value: 'Rydygiera', label: 'Rydygiera 6' },
]

const TIME_RANGES = [
  { value: 12, label: '1 rok' },
  { value: 24, label: '2 lata' },
  { value: 36, label: '3 lata' },
  { value: 0, label: 'Całość' },
]

const AGGREGATIONS = [
  { value: 'month', label: 'Miesięcznie' },
  { value: 'quarter', label: 'Kwartalnie' },
]

const MONTHS_PL = ['', 'Sty', 'Lut', 'Mar', 'Kwi', 'Maj', 'Cze', 'Lip', 'Sie', 'Wrz', 'Paź', 'Lis', 'Gru']
const QUARTERS_PL = { '01': 'Q1', '04': 'Q2', '07': 'Q3', '10': 'Q4' }

function toYearMonth(dateStr) {
  if (!dateStr) return null
  const [y, m] = dateStr.split('-')
  return `${y}-${m}`
}

function formatYM(ym) {
  if (!ym) return ''
  const [y, m] = ym.split('-')
  return `${MONTHS_PL[parseInt(m)]} ${y}`
}

function formatPeriodLabel(key, aggregation) {
  if (aggregation === 'quarter') {
    // key = "2023-Q1"
    const [y, q] = key.split('-')
    return `${q} ${y}`
  }
  return formatYM(key)
}

function toQuarter(ym) {
  const [y, m] = ym.split('-')
  const q = Math.ceil(parseInt(m) / 3)
  return `${y}-Q${q}`
}

function getMonthsBetween(startDate, endDate) {
  const [sy, sm] = startDate.split('-').map(Number)
  const [ey, em] = endDate.split('-').map(Number)
  const months = []
  let y = sy, m = sm
  while (y < ey || (y === ey && m <= em)) {
    months.push(`${y}-${String(m).padStart(2, '0')}`)
    m++
    if (m > 12) { m = 1; y++ }
  }
  return months.length > 0 ? months : [toYearMonth(startDate)]
}

function aggregateToQuarters(monthlyData) {
  const quarters = {}
  for (const row of monthlyData) {
    const qKey = toQuarter(row.month)
    if (!quarters[qKey]) quarters[qKey] = { period: qKey }
    for (const key of Object.keys(row)) {
      if (key === 'month' || key === 'period') continue
      quarters[qKey][key] = (quarters[qKey][key] || 0) + (row[key] || 0)
    }
  }
  return Object.values(quarters).sort((a, b) => a.period.localeCompare(b.period))
}

function addMonths(ym, n) {
  let [y, m] = ym.split('-').map(Number)
  m += n
  while (m > 12) { m -= 12; y++ }
  while (m < 1) { m += 12; y-- }
  return `${y}-${String(m).padStart(2, '0')}`
}

export default function Dashboard() {
  const [chartData, setChartData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [location, setLocation] = useState('Płatnicza 65')
  const [windowMonths, setWindowMonths] = useState(36) // 0 = all
  const [offset, setOffset] = useState(0) // 0 = most recent, positive = further back
  const [aggregation, setAggregation] = useState('month')

  useEffect(() => { loadData() }, [location])

  const loadData = async () => {
    setLoading(true)
    try {
      const data = await fetchChartData({ location: location || undefined })
      setChartData(data)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  // Build ALL monthly cost data (unfiltered)
  const allMonthly = useMemo(() => {
    if (!chartData?.series?.length) return []

    const providerMonths = {}
    for (const s of chartData.series) {
      const provider = s.provider
      for (const d of s.data) {
        if (d.is_estimate) continue
        const cost = d.cost_gross || 0
        if (!cost || !d.period_start) continue

        const months = getMonthsBetween(d.period_start, d.period_end || d.period_start)
        const perMonth = cost / months.length

        for (const ym of months) {
          if (!providerMonths[ym]) providerMonths[ym] = { month: ym }
          providerMonths[ym][provider] = (providerMonths[ym][provider] || 0) + perMonth
        }
      }
    }

    return Object.values(providerMonths)
      .sort((a, b) => a.month.localeCompare(b.month))
      .map(row => {
        const out = { month: row.month }
        for (const k of ['eon', 'pgnig', 'mpwik']) out[k] = Math.round((row[k] || 0) * 100) / 100
        return out
      })
  }, [chartData])

  // Compute visible window bounds
  const { windowStart, windowEnd, canGoBack, canGoForward } = useMemo(() => {
    if (!allMonthly.length) return { windowStart: null, windowEnd: null, canGoBack: false, canGoForward: false }
    const lastMonth = allMonthly[allMonthly.length - 1].month
    const firstMonth = allMonthly[0].month

    if (windowMonths === 0) return { windowStart: firstMonth, windowEnd: lastMonth, canGoBack: false, canGoForward: false }

    const end = addMonths(lastMonth, -offset)
    const start = addMonths(end, -(windowMonths - 1))

    return {
      windowStart: start,
      windowEnd: end,
      canGoBack: start > firstMonth,
      canGoForward: offset > 0,
    }
  }, [allMonthly, windowMonths, offset])

  // Filter + aggregate for display
  const { displayData, displayCumulative } = useMemo(() => {
    if (!allMonthly.length) return { displayData: [], displayCumulative: [] }

    let filtered = allMonthly
    if (windowMonths > 0 && windowStart && windowEnd) {
      filtered = allMonthly.filter(row => row.month >= windowStart && row.month <= windowEnd)
    }

    let chartRows
    if (aggregation === 'quarter') {
      chartRows = aggregateToQuarters(filtered)
    } else {
      chartRows = filtered.map(row => ({ period: row.month, eon: row.eon, pgnig: row.pgnig, mpwik: row.mpwik }))
    }

    const final = chartRows.map(r => ({
      period: r.period,
      eon: Math.round((r.eon || 0) * 100) / 100,
      pgnig: Math.round((r.pgnig || 0) * 100) / 100,
      mpwik: Math.round((r.mpwik || 0) * 100) / 100,
      total: Math.round(((r.eon || 0) + (r.pgnig || 0) + (r.mpwik || 0)) * 100) / 100,
    }))

    return { displayData: final, displayCumulative: final }
  }, [allMonthly, windowMonths, windowStart, windowEnd, aggregation])

  const handleWindowChange = (months) => {
    setWindowMonths(months)
    setOffset(0)
  }

  const stepSize = Math.max(1, Math.floor(windowMonths / 2))
  const goBack = () => setOffset(o => o + stepSize)
  const goForward = () => setOffset(o => Math.max(0, o - stepSize))

  const windowLabel = windowStart && windowEnd && windowMonths > 0
    ? `${formatYM(windowStart)} — ${formatYM(windowEnd)}`
    : 'Cały zakres'

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
      </div>
    )
  }

  if (!chartData?.series?.length) {
    return (
      <div className="text-center py-16 text-gray-500">
        <TrendingUp className="w-12 h-12 mx-auto mb-3 text-gray-300" />
        <p className="text-sm">Brak danych do wyświetlenia</p>
        <p className="text-xs mt-1">Najpierw zaimportuj faktury w zakładce "Pliki"</p>
      </div>
    )
  }

  // Per-utility series for detail charts
  const seriesByUtility = {}
  for (const s of chartData.series) {
    const key = s.utility_type
    if (!seriesByUtility[key]) seriesByUtility[key] = []
    seriesByUtility[key].push(s)
  }

  return (
    <div className="space-y-6">
      {/* Filters */}
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <Filter className="w-4 h-4 text-gray-500" />
          <select
            value={location}
            onChange={e => setLocation(e.target.value)}
            className="text-sm border border-gray-300 rounded-lg px-3 py-1.5 bg-white"
          >
            {LOCATIONS.map(l => (
              <option key={l.value} value={l.value}>{l.label}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Summary cards */}
      <SummaryCards series={chartData.series} windowStart={windowStart} windowEnd={windowEnd} />

      {/* ═══ TIME RANGE & AGGREGATION TOOLBAR ═══ */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm px-5 py-3 flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <Calendar className="w-4 h-4 text-gray-400" />
          <div className="flex bg-gray-100 rounded-lg p-0.5">
            {TIME_RANGES.map(tr => (
              <button
                key={tr.value}
                onClick={() => handleWindowChange(tr.value)}
                className={`px-3 py-1 text-xs font-medium rounded-md transition-colors cursor-pointer ${
                  windowMonths === tr.value
                    ? 'bg-white text-gray-900 shadow-sm'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                {tr.label}
              </button>
            ))}
          </div>

          {windowMonths > 0 && (
            <div className="flex items-center gap-1">
              <button
                onClick={goBack}
                disabled={!canGoBack}
                className="p-1 rounded-md hover:bg-gray-100 disabled:opacity-30 disabled:cursor-default cursor-pointer transition-colors"
              >
                <ChevronLeft className="w-4 h-4 text-gray-600" />
              </button>
              <span className="text-xs text-gray-600 font-medium min-w-[160px] text-center">
                {windowLabel}
              </span>
              <button
                onClick={goForward}
                disabled={!canGoForward}
                className="p-1 rounded-md hover:bg-gray-100 disabled:opacity-30 disabled:cursor-default cursor-pointer transition-colors"
              >
                <ChevronRight className="w-4 h-4 text-gray-600" />
              </button>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500 font-medium mr-1">Agregacja:</span>
          <div className="flex bg-gray-100 rounded-lg p-0.5">
            {AGGREGATIONS.map(ag => (
              <button
                key={ag.value}
                onClick={() => setAggregation(ag.value)}
                className={`px-3 py-1 text-xs font-medium rounded-md transition-colors cursor-pointer ${
                  aggregation === ag.value
                    ? 'bg-white text-gray-900 shadow-sm'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                {ag.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ═══ MAIN CHART 1: Provider costs over time (area, smoothed) ═══ */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="px-5 py-3 bg-gray-50 border-b border-gray-200">
          <h3 className="text-sm font-semibold text-gray-700">Koszty wg dostawcy w czasie</h3>
          <p className="text-xs text-gray-400">
            {aggregation === 'quarter' ? 'Kwartalnie' : 'Miesięcznie'} — prąd, gaz, woda (koszty rozłożone proporcjonalnie)
          </p>
        </div>
        <div className="p-4">
          <ResponsiveContainer width="100%" height={380}>
            <AreaChart data={displayData}>
              <defs>
                {Object.entries(PROVIDER_CONFIG).map(([key, cfg]) => (
                  <linearGradient key={key} id={`grad_${key}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={cfg.color} stopOpacity={0.3} />
                    <stop offset="95%" stopColor={cfg.color} stopOpacity={0.02} />
                  </linearGradient>
                ))}
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis
                dataKey="period"
                tickFormatter={v => formatPeriodLabel(v, aggregation)}
                tick={{ fontSize: 11 }}
                interval="preserveStartEnd"
              />
              <YAxis tick={{ fontSize: 11 }} tickFormatter={v => `${v} zł`} />
              <Tooltip content={<ProviderTooltip aggregation={aggregation} />} />
              <Legend formatter={(value) => PROVIDER_CONFIG[value]?.label || value} />
              {Object.entries(PROVIDER_CONFIG).map(([key, cfg]) => (
                <Area
                  key={key}
                  type="monotone"
                  dataKey={key}
                  name={key}
                  stroke={cfg.color}
                  strokeWidth={2.5}
                  fill={`url(#grad_${key})`}
                  connectNulls
                  dot={false}
                  activeDot={{ r: 5, strokeWidth: 2 }}
                />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* ═══ MAIN CHART 2: Cumulative costs (stacked bar) ═══ */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="px-5 py-3 bg-gray-50 border-b border-gray-200">
          <h3 className="text-sm font-semibold text-gray-700">
            Łączne koszty {aggregation === 'quarter' ? 'kwartalne' : 'miesięczne'}
          </h3>
          <p className="text-xs text-gray-400">Kumulacja kosztów wszystkich dostawców</p>
        </div>
        <div className="p-4">
          <ResponsiveContainer width="100%" height={380}>
            <BarChart data={displayCumulative}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis
                dataKey="period"
                tickFormatter={v => formatPeriodLabel(v, aggregation)}
                tick={{ fontSize: 11 }}
                interval="preserveStartEnd"
              />
              <YAxis tick={{ fontSize: 11 }} tickFormatter={v => `${v} zł`} />
              <Tooltip content={<CumulativeTooltip aggregation={aggregation} />} />
              <Legend formatter={(value) => PROVIDER_CONFIG[value]?.label || value} />
              {Object.entries(PROVIDER_CONFIG).map(([key, cfg]) => (
                <Bar
                  key={key}
                  dataKey={key}
                  name={key}
                  stackId="costs"
                  fill={cfg.color}
                  opacity={0.85}
                  radius={key === 'mpwik' ? [4, 4, 0, 0] : [0, 0, 0, 0]}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* ═══ DETAIL CHARTS per utility type ═══ */}
      {Object.entries(seriesByUtility).map(([utilityType, seriesList]) => (
        <UtilityCharts
          key={utilityType}
          utilityType={utilityType}
          seriesList={seriesList}
          windowStart={windowStart}
          windowEnd={windowEnd}
          windowMonths={windowMonths}
        />
      ))}
    </div>
  )
}

function ProviderTooltip({ active, payload, label, aggregation }) {
  if (!active || !payload?.length) return null
  const total = payload.reduce((s, p) => s + (p.value || 0), 0)
  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-lg p-3 text-sm min-w-[180px]">
      <p className="font-medium text-gray-800 mb-2">{formatPeriodLabel(label, aggregation)}</p>
      {payload.map((p, i) => (
        <div key={i} className="flex justify-between gap-4" style={{ color: p.color }}>
          <span>{PROVIDER_CONFIG[p.dataKey]?.label || p.dataKey}</span>
          <span className="font-semibold">{p.value?.toFixed(0)} zł</span>
        </div>
      ))}
      <div className="border-t border-gray-100 mt-1.5 pt-1.5 flex justify-between font-bold text-gray-800">
        <span>Razem</span>
        <span>{total.toFixed(0)} zł</span>
      </div>
    </div>
  )
}

function CumulativeTooltip({ active, payload, label, aggregation }) {
  if (!active || !payload?.length) return null
  const total = payload.reduce((s, p) => s + (p.value || 0), 0)
  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-lg p-3 text-sm min-w-[180px]">
      <p className="font-medium text-gray-800 mb-2">{formatPeriodLabel(label, aggregation)}</p>
      {payload.filter(p => p.value > 0).map((p, i) => (
        <div key={i} className="flex justify-between gap-4" style={{ color: p.color }}>
          <span>{PROVIDER_CONFIG[p.dataKey]?.label || p.dataKey}</span>
          <span className="font-semibold">{p.value?.toFixed(0)} zł</span>
        </div>
      ))}
      <div className="border-t border-gray-100 mt-1.5 pt-1.5 flex justify-between font-bold text-gray-800">
        <span>Razem</span>
        <span>{total.toFixed(0)} zł</span>
      </div>
    </div>
  )
}

function SummaryCards({ series, windowStart, windowEnd }) {
  const summaries = []

  // Group by provider
  const byProvider = {}
  for (const s of series) {
    const p = s.provider
    if (!byProvider[p]) byProvider[p] = []
    byProvider[p].push(s)
  }

  for (const [provider, provSeries] of Object.entries(byProvider)) {
    const cfg = PROVIDER_CONFIG[provider]
    if (!cfg) continue

    let allData = provSeries.flatMap(s => s.data.filter(d => !d.is_estimate))
    if (allData.length === 0) continue

    // Filter by window period if specified
    if (windowStart && windowEnd) {
      allData = allData.filter(d => {
        if (!d.period_start) return false
        const months = getMonthsBetween(d.period_start, d.period_end || d.period_start)
        // Include invoice if any of its months fall within the window
        return months.some(ym => ym >= windowStart && ym <= windowEnd)
      })
    }

    // Calculate total cost for filtered data, proportionally distributed across months
    let totalCost = 0
    for (const d of allData) {
      const cost = d.cost_gross || 0
      if (!cost || !d.period_start) continue
      
      const months = getMonthsBetween(d.period_start, d.period_end || d.period_start)
      if (windowStart && windowEnd) {
        // Count only months within the window
        const monthsInWindow = months.filter(ym => ym >= windowStart && ym <= windowEnd)
        const perMonth = cost / months.length
        totalCost += perMonth * monthsInWindow.length
      } else {
        totalCost += cost
      }
    }
    const sorted = [...allData].sort((a, b) => (a.period_start || '').localeCompare(b.period_start || ''))
    const lastRecord = sorted[sorted.length - 1]
    const prevRecord = sorted.length > 1 ? sorted[sorted.length - 2] : null

    let costTrend = null
    if (prevRecord && lastRecord.cost_gross && prevRecord.cost_gross) {
      costTrend = ((lastRecord.cost_gross - prevRecord.cost_gross) / prevRecord.cost_gross * 100).toFixed(0)
    }

    summaries.push({
      key: provider,
      label: cfg.label,
      icon: cfg.icon,
      color: cfg.color,
      totalCost,
      records: allData.length,
      lastCost: lastRecord.cost_gross,
      costTrend,
    })
  }

  if (summaries.length === 0) return null

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      {summaries.map(s => {
        const Icon = s.icon
        const TrendIcon = s.costTrend > 0 ? TrendingUp : s.costTrend < 0 ? TrendingDown : Minus
        const trendColor = s.costTrend > 0 ? 'text-red-600' : s.costTrend < 0 ? 'text-green-600' : 'text-gray-500'

        return (
          <div key={s.key} className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
            <div className="flex items-center gap-2 mb-3">
              <div className="p-2 rounded-lg" style={{ backgroundColor: `${s.color}18` }}>
                <Icon className="w-5 h-5" style={{ color: s.color }} />
              </div>
              <span className="font-medium text-gray-700">{s.label}</span>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <p className="text-xs text-gray-500">Łączny koszt</p>
                <p className="text-xl font-bold text-gray-900">{s.totalCost.toFixed(0)} zł</p>
              </div>
              <div>
                <p className="text-xs text-gray-500">Ostatni rachunek</p>
                <p className="text-lg font-semibold text-gray-800">
                  {s.lastCost?.toFixed(0)} zł
                </p>
              </div>
            </div>
            <div className="flex items-center justify-between mt-2">
              <p className="text-xs text-gray-400">{s.records} faktur</p>
              {s.costTrend !== null && (
                <p className={`text-xs font-semibold flex items-center gap-1 ${trendColor}`}>
                  <TrendIcon className="w-3 h-3" />
                  {Math.abs(s.costTrend)}% vs poprzedni
                </p>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function UtilityCharts({ utilityType, seriesList, windowStart, windowEnd, windowMonths }) {
  const providerKey = seriesList[0]?.provider
  const cfg = PROVIDER_CONFIG[providerKey] || PROVIDER_CONFIG.eon
  const Icon = cfg.icon

  const allLocations = [...new Set(seriesList.map(s => s.location).filter(Boolean))]
  // Shade variants of the provider color for multiple locations
  const locColors = allLocations.length > 1
    ? [cfg.color, `${cfg.color}99`]
    : [cfg.color]

  const periodMap = {}
  for (const s of seriesList) {
    for (const d of s.data) {
      if (d.is_estimate) continue
      const key = d.period_start
      if (!key) continue
      // Apply time window filter (use period_start's YYYY-MM)
      const ym = toYearMonth(key)
      if (windowMonths > 0 && windowStart && windowEnd) {
        if (ym < windowStart || ym > windowEnd) continue
      }
      if (!periodMap[key]) {
        periodMap[key] = { period: key }
      }
      const locKey = (s.location || 'unknown').replace(/\s+/g, '_')
      periodMap[key][`cost_${locKey}`] = d.cost_gross
      periodMap[key][`kwh_${locKey}`] = d.consumption_kwh || d.consumption_value
    }
  }

  const chartPoints = Object.values(periodMap).sort((a, b) => a.period.localeCompare(b.period))

  const formatPeriod = (period) => {
    if (!period) return ''
    const [y, m] = period.split('-')
    return `${MONTHS_PL[parseInt(m)]} ${y.slice(2)}`
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
      <div className="px-4 py-3 bg-gray-50 border-b border-gray-200 flex items-center gap-2">
        <Icon className="w-4 h-4" style={{ color: cfg.color }} />
        <h3 className="text-sm font-semibold text-gray-700">{cfg.label} — szczegóły</h3>
      </div>

      <div className="p-4 space-y-6">
        <div>
          <h4 className="text-xs font-medium text-gray-500 mb-2 uppercase tracking-wide">Koszty brutto (PLN)</h4>
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart data={chartPoints}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="period" tickFormatter={formatPeriod} tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip
                formatter={(v, name) => [`${v?.toFixed(2)} zł`, name]}
                labelFormatter={formatPeriod}
              />
              <Legend />
              {allLocations.map((loc, i) => {
                const locKey = loc.replace(/\s+/g, '_')
                return (
                  <Bar
                    key={loc}
                    dataKey={`cost_${locKey}`}
                    name={loc}
                    fill={locColors[i % locColors.length]}
                    radius={[4, 4, 0, 0]}
                    opacity={0.85}
                  />
                )
              })}
            </ComposedChart>
          </ResponsiveContainer>
        </div>

        <div>
          <h4 className="text-xs font-medium text-gray-500 mb-2 uppercase tracking-wide">
            Zużycie ({cfg.unit})
          </h4>
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart data={chartPoints}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="period" tickFormatter={formatPeriod} tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip
                formatter={(v, name) => [`${v?.toFixed(1)} ${cfg.unit}`, name]}
                labelFormatter={formatPeriod}
              />
              <Legend />
              {allLocations.map((loc, i) => {
                const locKey = loc.replace(/\s+/g, '_')
                return (
                  <Line
                    key={loc}
                    type="monotone"
                    dataKey={`kwh_${locKey}`}
                    name={loc}
                    stroke={locColors[i % locColors.length]}
                    strokeWidth={2}
                    dot={{ r: 3 }}
                    connectNulls
                  />
                )
              })}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}
