import { useState } from 'react'
import './App.css'
import Dashboard from './components/Dashboard'
import FileManager from './components/FileManager'
import DocumentList from './components/DocumentList'
import { Zap, Flame, Droplets, FolderOpen, BarChart3, FileText } from 'lucide-react'

const TABS = [
  { id: 'dashboard', label: 'Dashboard', icon: BarChart3 },
  { id: 'files', label: 'Pliki', icon: FolderOpen },
  { id: 'documents', label: 'Dokumenty', icon: FileText },
]

function App() {
  const [activeTab, setActiveTab] = useState('dashboard')
  const [refreshKey, setRefreshKey] = useState(0)

  const handleDataChanged = () => setRefreshKey(k => k + 1)

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1">
              <Zap className="w-6 h-6 text-yellow-500" />
              <Flame className="w-6 h-6 text-orange-500" />
              <Droplets className="w-6 h-6 text-blue-500" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-gray-900">Rachunki</h1>
              <p className="text-xs text-gray-500">Analiza mediów domowych</p>
            </div>
          </div>

          {/* Tab navigation */}
          <nav className="flex gap-1">
            {TABS.map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors cursor-pointer ${
                  activeTab === tab.id
                    ? 'bg-blue-50 text-blue-700'
                    : 'text-gray-600 hover:bg-gray-100'
                }`}
              >
                <tab.icon className="w-4 h-4" />
                {tab.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      {/* Content */}
      <main className="max-w-7xl mx-auto px-4 py-6">
        {activeTab === 'dashboard' && <Dashboard key={refreshKey} />}
        {activeTab === 'files' && <FileManager onDataChanged={handleDataChanged} />}
        {activeTab === 'documents' && <DocumentList key={refreshKey} />}
      </main>
    </div>
  )
}

export default App
