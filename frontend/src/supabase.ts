import { createClient } from '@supabase/supabase-js'

// The project's URL and anon key are public by design: they only let the browser log in.
// What a user may read is decided by the backend, and Supabase's own REST API is closed (RLS on every table).
const SUPABASE_URL = 'https://qnzdejhsxdtqnfelmrbq.supabase.co'
const SUPABASE_ANON_KEY =
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFuemRlamhzeGR0cW5mZWxtcmJxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTEyMDIxOTIsImV4cCI6MjEwNjc3ODE5Mn0.qVw3NdHH6TTRW5Uuh078TwxG7EGxjJOaK08mK7vUUVc'

export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY)
