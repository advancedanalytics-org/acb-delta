import { Navigate } from 'react-router'

/** Direct access to /review redirects back to inbox so user selects a VBPL first. */
export function ReviewIndexRedirect() {
  return <Navigate to="/" replace />
}
