import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  // Sert les fichiers statiques depuis data/ (forest_kg.ttl accessible en /forest_kg.ttl)
  publicDir: path.resolve(__dirname, '../data'),
})
