/** Short git label for UI/build banners. Used by Vite configs at startup. */
import { execSync } from 'node:child_process'

export function shepherdVersion() {
  try {
    const sha = execSync('git rev-parse --short HEAD', {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim()
    const branch = execSync('git rev-parse --abbrev-ref HEAD', {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim()
    if (!sha) return 'dev'
    return branch && branch !== 'HEAD' ? `${branch}@${sha}` : sha
  } catch {
    return 'dev'
  }
}
