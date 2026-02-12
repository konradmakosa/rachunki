import { useState, useEffect } from 'react'
import { fetchDocuments, fetchConsumption } from '../api'
import { FileText, Zap, Flame, ChevronDown, ChevronUp } from 'lucide-react'

const PROVIDER_CFG = {
  eon: { label: 'e.on', color: 'bg-yellow-100 text-yellow-800', icon: Zap },
  pgnig: { label: 'PGNiG', color: 'bg-orange-100 text-orange-800', icon: Flame },
}

const DOC_TYPE_LABELS = {
  faktura_rozliczeniowa: 'Faktura rozliczeniowa',
  prognoza: 'Prognoza',
  nota_odsetkowa: 'Nota odsetkowa',
  wplata: 'Wpłata',
}

export default function DocumentList() {
  const [documents, setDocuments] = useState([])
  const [consumption, setConsumption] = useState([])
  const [loading, setLoading] = useState(true)
  const [view, setView] = useState('consumption') // 'documents' | 'consumption'

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    setLoading(true)
    try {
      const [docs, cons] = await Promise.all([
        fetchDocuments(),
        fetchConsumption(),
      ])
      setDocuments(docs.documents || [])
      setConsumption(cons.records || [])
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* View toggle */}
      <div className="flex gap-2">
        <button
          onClick={() => setView('consumption')}
          className={`px-4 py-2 rounded-lg text-sm font-medium cursor-pointer ${
            view === 'consumption' ? 'bg-blue-50 text-blue-700' : 'bg-white text-gray-600 border border-gray-200'
          }`}
        >
          Zużycie ({consumption.length})
        </button>
        <button
          onClick={() => setView('documents')}
          className={`px-4 py-2 rounded-lg text-sm font-medium cursor-pointer ${
            view === 'documents' ? 'bg-blue-50 text-blue-700' : 'bg-white text-gray-600 border border-gray-200'
          }`}
        >
          Dokumenty ({documents.length})
        </button>
      </div>

      {view === 'consumption' ? (
        <ConsumptionTable records={consumption} />
      ) : (
        <DocumentsTable documents={documents} />
      )}
    </div>
  )
}

function ConsumptionTable({ records }) {
  if (records.length === 0) {
    return <EmptyState message="Brak rekordów zużycia" />
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200">
              <th className="text-left px-4 py-2.5 font-medium text-gray-600">Dostawca</th>
              <th className="text-left px-4 py-2.5 font-medium text-gray-600">Medium</th>
              <th className="text-left px-4 py-2.5 font-medium text-gray-600">Lokalizacja</th>
              <th className="text-left px-4 py-2.5 font-medium text-gray-600">Okres</th>
              <th className="text-right px-4 py-2.5 font-medium text-gray-600">Zużycie</th>
              <th className="text-right px-4 py-2.5 font-medium text-gray-600">Koszt netto</th>
              <th className="text-right px-4 py-2.5 font-medium text-gray-600">Koszt brutto</th>
              <th className="text-center px-4 py-2.5 font-medium text-gray-600">Typ</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {records.map((r) => {
              const cfg = PROVIDER_CFG[r.provider] || {}
              const Icon = cfg.icon || FileText
              return (
                <tr key={r.id} className={`hover:bg-gray-50 ${r.is_estimate ? 'opacity-60' : ''}`}>
                  <td className="px-4 py-2.5">
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${cfg.color || 'bg-gray-100'}`}>
                      <Icon className="w-3 h-3" />
                      {cfg.label || r.provider}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-gray-700">
                    {r.utility_type === 'electricity' ? '⚡ Prąd' : '🔥 Gaz'}
                  </td>
                  <td className="px-4 py-2.5 text-gray-700">{r.location}</td>
                  <td className="px-4 py-2.5 text-gray-700 whitespace-nowrap">
                    {r.period_start} — {r.period_end}
                  </td>
                  <td className="px-4 py-2.5 text-right text-gray-900 font-medium whitespace-nowrap">
                    {r.consumption_kwh ? `${r.consumption_kwh.toFixed(0)} kWh` : ''}
                    {r.consumption_value && r.consumption_unit === 'm3' ? (
                      <span className="text-gray-500 text-xs ml-1">({r.consumption_value} m³)</span>
                    ) : null}
                  </td>
                  <td className="px-4 py-2.5 text-right text-gray-700">
                    {r.cost_net ? `${r.cost_net.toFixed(2)} zł` : '—'}
                  </td>
                  <td className="px-4 py-2.5 text-right text-gray-900 font-medium">
                    {r.cost_gross ? `${r.cost_gross.toFixed(2)} zł` : '—'}
                  </td>
                  <td className="px-4 py-2.5 text-center">
                    {r.is_estimate ? (
                      <span className="text-xs px-2 py-0.5 bg-amber-50 text-amber-700 rounded-full">prognoza</span>
                    ) : (
                      <span className="text-xs px-2 py-0.5 bg-green-50 text-green-700 rounded-full">rzeczywiste</span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function DocumentsTable({ documents }) {
  if (documents.length === 0) {
    return <EmptyState message="Brak zaimportowanych dokumentów" />
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200">
              <th className="text-left px-4 py-2.5 font-medium text-gray-600">Dostawca</th>
              <th className="text-left px-4 py-2.5 font-medium text-gray-600">Typ</th>
              <th className="text-left px-4 py-2.5 font-medium text-gray-600">Nr dokumentu</th>
              <th className="text-left px-4 py-2.5 font-medium text-gray-600">Data wystawienia</th>
              <th className="text-right px-4 py-2.5 font-medium text-gray-600">Kwota</th>
              <th className="text-left px-4 py-2.5 font-medium text-gray-600">Lokalizacja</th>
              <th className="text-left px-4 py-2.5 font-medium text-gray-600">Plik</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {documents.map((d) => {
              const cfg = PROVIDER_CFG[d.provider] || {}
              const Icon = cfg.icon || FileText
              return (
                <tr key={d.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2.5">
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${cfg.color || 'bg-gray-100'}`}>
                      <Icon className="w-3 h-3" />
                      {cfg.label || d.provider}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-gray-700">
                    {DOC_TYPE_LABELS[d.doc_type] || d.doc_type}
                  </td>
                  <td className="px-4 py-2.5 text-gray-700 font-mono text-xs">{d.doc_number}</td>
                  <td className="px-4 py-2.5 text-gray-700">{d.issue_date}</td>
                  <td className="px-4 py-2.5 text-right text-gray-900 font-medium">
                    {d.amount_pln ? `${d.amount_pln.toFixed(2)} zł` : '—'}
                  </td>
                  <td className="px-4 py-2.5 text-gray-700">{d.location}</td>
                  <td className="px-4 py-2.5 text-gray-500 text-xs truncate max-w-48">{d.filename}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function EmptyState({ message }) {
  return (
    <div className="text-center py-16 text-gray-500">
      <FileText className="w-12 h-12 mx-auto mb-3 text-gray-300" />
      <p className="text-sm">{message}</p>
      <p className="text-xs mt-1">Zaimportuj faktury w zakładce "Pliki"</p>
    </div>
  )
}
