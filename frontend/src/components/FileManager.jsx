import { useState, useEffect } from 'react'
import { scanGdrive, processFile, uploadFile } from '../api'
import { FolderSearch, Upload, Play, CheckCircle, XCircle, Loader2, FileText, Zap, Flame } from 'lucide-react'

const PROVIDER_BADGE = {
  eon: { label: 'e.on', color: 'bg-yellow-100 text-yellow-800', icon: Zap },
  pgnig: { label: 'PGNiG', color: 'bg-orange-100 text-orange-800', icon: Flame },
  unknown: { label: '?', color: 'bg-gray-100 text-gray-800', icon: FileText },
}

export default function FileManager({ onDataChanged }) {
  const [files, setFiles] = useState([])
  const [scanning, setScanning] = useState(false)
  const [processing, setProcessing] = useState({}) // filepath -> status
  const [results, setResults] = useState({}) // filepath -> result
  const [error, setError] = useState(null)

  const handleScan = async () => {
    setScanning(true)
    setError(null)
    try {
      const data = await scanGdrive()
      setFiles(data.files || [])
    } catch (e) {
      setError(e.message)
    } finally {
      setScanning(false)
    }
  }

  const handleProcess = async (filepath, useAi = false) => {
    setProcessing(p => ({ ...p, [filepath]: 'loading' }))
    try {
      const result = await processFile(filepath, useAi)
      setProcessing(p => ({ ...p, [filepath]: 'done' }))
      setResults(r => ({ ...r, [filepath]: result }))
      onDataChanged?.()
    } catch (e) {
      setProcessing(p => ({ ...p, [filepath]: 'error' }))
      setResults(r => ({ ...r, [filepath]: { error: e.message } }))
    }
  }

  const handleProcessAll = async () => {
    for (const file of files) {
      if (processing[file.path] === 'done') continue
      await handleProcess(file.path)
    }
  }

  const handleUpload = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    try {
      const result = await uploadFile(file)
      await handleProcess(result.path)
    } catch (e) {
      setError(e.message)
    }
  }

  const formatSize = (bytes) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  return (
    <div className="space-y-6">
      {/* Actions bar */}
      <div className="flex items-center gap-3 flex-wrap">
        <button
          onClick={handleScan}
          disabled={scanning}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm font-medium cursor-pointer"
        >
          {scanning ? <Loader2 className="w-4 h-4 animate-spin" /> : <FolderSearch className="w-4 h-4" />}
          Skanuj Google Drive
        </button>

        {files.length > 0 && (
          <button
            onClick={handleProcessAll}
            className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 text-sm font-medium cursor-pointer"
          >
            <Play className="w-4 h-4" />
            Przetwórz wszystkie ({files.length})
          </button>
        )}

        <label className="flex items-center gap-2 px-4 py-2 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 text-sm font-medium cursor-pointer">
          <Upload className="w-4 h-4 text-gray-600" />
          <span className="text-gray-700">Wgraj plik</span>
          <input type="file" accept=".pdf,.xlsx,.mhtml,.html" onChange={handleUpload} className="hidden" />
        </label>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">
          {error}
        </div>
      )}

      {/* File list */}
      {files.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="px-4 py-3 bg-gray-50 border-b border-gray-200">
            <h3 className="text-sm font-semibold text-gray-700">
              Znalezione pliki ({files.length})
            </h3>
          </div>
          <div className="divide-y divide-gray-100">
            {files.map((file) => {
              const badge = PROVIDER_BADGE[file.provider] || PROVIDER_BADGE.unknown
              const status = processing[file.path]
              const result = results[file.path]
              const BadgeIcon = badge.icon

              return (
                <div key={file.path} className="px-4 py-3 flex items-center gap-3 hover:bg-gray-50">
                  <FileText className="w-5 h-5 text-gray-400 shrink-0" />

                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">{file.filename}</p>
                    <p className="text-xs text-gray-500">{formatSize(file.size)}</p>
                  </div>

                  <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${badge.color}`}>
                    <BadgeIcon className="w-3 h-3" />
                    {badge.label}
                  </span>

                  {status === 'done' ? (
                    <CheckCircle className="w-5 h-5 text-green-500 shrink-0" />
                  ) : status === 'error' ? (
                    <div className="flex items-center gap-2">
                      <XCircle className="w-5 h-5 text-red-500 shrink-0" />
                      <span className="text-xs text-red-600 max-w-48 truncate">{result?.error}</span>
                    </div>
                  ) : status === 'loading' ? (
                    <Loader2 className="w-5 h-5 text-blue-500 animate-spin shrink-0" />
                  ) : (
                    <button
                      onClick={() => handleProcess(file.path)}
                      className="text-xs px-3 py-1 bg-blue-50 text-blue-700 rounded-md hover:bg-blue-100 font-medium cursor-pointer"
                    >
                      Przetwórz
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Results preview */}
      {Object.keys(results).length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="px-4 py-3 bg-gray-50 border-b border-gray-200">
            <h3 className="text-sm font-semibold text-gray-700">Wyniki przetwarzania</h3>
          </div>
          <div className="p-4 space-y-3">
            {Object.entries(results).map(([path, result]) => {
              if (result.error) return null
              const filename = path.split('/').pop()
              return (
                <div key={path} className="text-sm">
                  <p className="font-medium text-gray-800">{filename}</p>
                  {result.parsed && (
                    <div className="mt-1 grid grid-cols-2 md:grid-cols-4 gap-2 text-xs text-gray-600">
                      {result.parsed.doc_number && <span>Nr: {result.parsed.doc_number}</span>}
                      {result.parsed.period_start && (
                        <span>Okres: {result.parsed.period_start} — {result.parsed.period_end}</span>
                      )}
                      {result.parsed.consumption_kwh > 0 && (
                        <span>Zużycie: {result.parsed.consumption_kwh} kWh</span>
                      )}
                      {result.parsed.consumption?.kwh > 0 && (
                        <span>Zużycie: {result.parsed.consumption.kwh} kWh</span>
                      )}
                      {result.parsed.cost_gross > 0 && (
                        <span>Koszt: {result.parsed.cost_gross?.toFixed(2)} PLN</span>
                      )}
                    </div>
                  )}
                  {result.documents !== undefined && (
                    <p className="text-xs text-gray-500 mt-1">
                      Zaimportowano {result.documents} dokumentów, {result.consumption_records} rekordów zużycia
                    </p>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {files.length === 0 && !scanning && (
        <div className="text-center py-16 text-gray-500">
          <FolderSearch className="w-12 h-12 mx-auto mb-3 text-gray-300" />
          <p className="text-sm">Kliknij "Skanuj Google Drive" aby znaleźć faktury</p>
          <p className="text-xs mt-1">lub wgraj pliki ręcznie</p>
        </div>
      )}
    </div>
  )
}
