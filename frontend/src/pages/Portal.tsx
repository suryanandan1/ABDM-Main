import { useEffect, useState } from 'react'
import {
  Alert, Box, Button, Chip, Grid2 as Grid, Paper, Skeleton, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography,
} from '@mui/material'
import { api, errorMessage, formatAbha, formatDate, formatDateTime, GENDERS } from '../api'
import { useAuth } from '../auth'
import { PageHeader } from '../components/ui'

interface Doctor { full_name: string; specialization?: string | null }
interface HospitalRecord {
  hospital_name: string
  profile: {
    patient_code: string; full_name: string; gender: keyof typeof GENDERS; date_of_birth: string | null; year_of_birth: number
    mobile: string; address_line: string | null; city: string | null; state: string | null; pincode: string | null
    abha_number: string | null; abha_address: string | null; abha_verified: boolean
    emergency_contact_name: string | null; emergency_contact_phone: string | null; emergency_contact_relation: string | null
  }
  visits: {
    id: number; visit_at: string; doctor: Doctor; chief_complaint: string | null; clinical_findings: string | null
    vitals: Record<string, number> | null; treatment_plan: string | null; follow_up_instructions: string | null
    follow_up_date: string | null; conditions: { id: number; display: string; code: string | null; clinical_status: string }[]
  }[]
  prescriptions: {
    id: number; prescription_date: string; doctor: Doctor; notes: string | null
    items: { id: number; medicine_name: string; dosage: string; route: string; frequency: string; duration_days: number
      instructions: string | null }[]
  }[]
  lab_reports: {
    id: number; test_name: string; ordered_at: string; approved_at: string | null; conclusion: string | null
    results: { code: string; name: string; value: string; unit: string | null; ref_low: number | null; ref_high: number | null
      ref_text: string | null; interpretation: string | null }[]
  }[]
}

interface Consent {
  id: number; hospital_name: string; requester: string; purpose: string; hi_types: string[]; date_from: string
  date_to: string; data_erase_at: string; reason: string | null; status: string; status_message: string | null; created_at: string
}

const HI_LABEL: Record<string, string> = {
  OPConsultation: 'Consultations', Prescription: 'Prescriptions', DiagnosticReport: 'Lab reports',
  DischargeSummary: 'Discharge summaries', ImmunizationRecord: 'Immunisations', HealthDocumentRecord: 'Health documents',
  WellnessRecord: 'Wellness records',
}
const CONSENT_STATUS: Record<string, { label: string; color: 'warning' | 'success' | 'error' | 'default' | 'info' }> = {
  pending_consent: { label: 'Waiting for you', color: 'warning' }, received: { label: 'Shared', color: 'success' },
  granted: { label: 'Approved', color: 'success' }, retrieving: { label: 'Approved', color: 'success' },
  denied: { label: 'Denied', color: 'error' }, revoked: { label: 'Revoked', color: 'default' },
  failed: { label: 'Could not share', color: 'error' }, expired: { label: 'Expired', color: 'default' },
}

function Consents() {
  const [data, setData] = useState<Consent[] | null>(null)
  const [busy, setBusy] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const load = () => api.get('/portal/consents').then((r) => setData(r.data)).catch((e) => setError(errorMessage(e)))
  useEffect(() => { load() }, [])

  const act = async (c: Consent, path: string, body: object | undefined, done: string, confirmText?: string) => {
    if (confirmText && !window.confirm(confirmText)) return
    setBusy(c.id); setError(''); setMessage('')
    try { await api.post(`/portal/consents/${c.id}/${path}`, body); setMessage(done); await load() }
    catch (e) { setError(errorMessage(e)) } finally { setBusy(null) }
  }

  if (!data) return error ? <Alert severity="error">{error}</Alert> : <Skeleton variant="rounded" height={80} sx={{ mb: 2 }} />
  return (
    <Section title="Consent requests" empty={false}>
      {data.length === 0 && <Typography color="text.secondary">No hospital has asked to see your records.</Typography>}
      {message && <Alert severity="success" sx={{ mb: 1 }} onClose={() => setMessage('')}>{message}</Alert>}
      {error && <Alert severity="error" sx={{ mb: 1 }} onClose={() => setError('')}>{error}</Alert>}
      <Stack spacing={2}>
        {data.map((c) => {
          const status = CONSENT_STATUS[c.status] ?? { label: c.status, color: 'default' as const }
          return (
            <Paper key={c.id} variant="outlined" sx={{ p: 2, borderColor: c.status === 'pending_consent' ? 'warning.main' : undefined }}>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1, flexWrap: 'wrap' }} useFlexGap>
                <Typography fontWeight={600}>{c.hospital_name}</Typography>
                <Chip size="small" color={status.color} label={status.label} />
              </Stack>
              <Typography variant="body2"><b>Requested by:</b> {c.requester} · {formatDate(c.created_at)}</Typography>
              <Typography variant="body2"><b>Purpose:</b> {c.purpose}{c.reason ? ` — ${c.reason}` : ''}</Typography>
              <Typography variant="body2"><b>Records:</b> {c.hi_types.map((t) => HI_LABEL[t] ?? t).join(', ')}</Typography>
              <Typography variant="body2"><b>From:</b> {formatDate(c.date_from)} to {formatDate(c.date_to)}</Typography>
              <Typography variant="body2"><b>They may keep it until:</b> {formatDate(c.data_erase_at)}</Typography>
              {c.status_message && <Typography variant="body2" color="text.secondary">{c.status_message}</Typography>}
              {c.status === 'pending_consent' && (
                <Stack direction="row" spacing={1} sx={{ mt: 1.5, flexWrap: 'wrap' }} useFlexGap>
                  <Button variant="contained" color="success" disabled={busy === c.id}
                    onClick={() => act(c, 'decide', { grant: true }, 'Consent given. Your records have been shared.')}>Approve</Button>
                  {c.hi_types.length > 1 && c.hi_types.map((t) => (
                    <Button key={t} variant="outlined" disabled={busy === c.id}
                      onClick={() => act(c, 'decide', { grant: true, hi_types: [t] }, `Consent given for ${HI_LABEL[t] ?? t} only.`)}>
                      Only {HI_LABEL[t] ?? t}</Button>
                  ))}
                  <Button variant="outlined" color="error" disabled={busy === c.id}
                    onClick={() => act(c, 'decide', { grant: false }, 'Request denied. Nothing was shared.')}>Deny</Button>
                </Stack>
              )}
              {['granted', 'retrieving', 'received'].includes(c.status) && (
                <Button sx={{ mt: 1.5 }} variant="outlined" color="error" disabled={busy === c.id}
                  onClick={() => act(c, 'revoke', undefined, "Consent revoked. The hospital's copy of your records was erased.",
                    `Revoke consent for ${c.hospital_name}? Their copy of your records will be erased.`)}>Revoke consent</Button>
              )}
            </Paper>
          )
        })}
      </Stack>
    </Section>
  )
}

const VITALS: Record<string, string> = {
  temperature: 'Temperature (°C)', pulse: 'Pulse (/min)', systolic_bp: 'BP systolic', diastolic_bp: 'BP diastolic',
  spo2: 'SpO₂ (%)', weight: 'Weight (kg)', height: 'Height (cm)', respiratory_rate: 'Resp. rate (/min)',
}

function Section({ title, empty, children }: { title: string; empty: boolean; children: React.ReactNode }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
      <Typography variant="h6" gutterBottom>{title}</Typography>
      {empty ? <Typography color="text.secondary">Nothing here yet.</Typography> : children}
    </Paper>
  )
}

export default function Portal() {
  const { user } = useAuth()
  const [data, setData] = useState<{ abha_address: string; hospitals: HospitalRecord[] } | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.get('/portal/me').then((r) => setData(r.data)).catch((e) => setError(errorMessage(e)))
  }, [])

  if (error) return <Alert severity="error">{error}</Alert>
  if (!data) return <Skeleton variant="rounded" height={300} />
  return (
    <Box>
      <PageHeader title="My Health Record" />
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        {user?.full_name} · ABHA address <b>{data.abha_address}</b> · only records your doctors have approved are shown.
      </Typography>
      <Consents />
      {data.hospitals.length === 0 && (
        <Alert severity="info" sx={{ mb: 2 }}>No hospital has verified your ABHA address yet. When a hospital registers you
          with {data.abha_address} and verifies it, your records from that hospital appear here.</Alert>
      )}
      {data.hospitals.map((h) => (
        <Box key={h.profile.patient_code} sx={{ mb: 3 }}>
          <Typography variant="h5" sx={{ mb: 1 }}>{h.hospital_name}</Typography>
          <HospitalBlock data={h} />
        </Box>
      ))}
    </Box>
  )
}

function HospitalBlock({ data }: { data: HospitalRecord }) {
  const p = data.profile
  const field = (label: string, value: string | null | undefined) => (
    <Grid size={{ xs: 12, sm: 6, md: 4 }}>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography>{value || '—'}</Typography>
    </Grid>
  )

  return (
    <Box>
      <Section title="My details" empty={false}>
        <Grid container spacing={2}>
          {field('Name', p.full_name)}
          {field('Patient ID', p.patient_code)}
          {field('Gender', GENDERS[p.gender])}
          {field('Date of birth', p.date_of_birth ? formatDate(p.date_of_birth) : String(p.year_of_birth))}
          {field('Mobile', p.mobile)}
          {field('Address', [p.address_line, p.city, p.state, p.pincode].filter(Boolean).join(', '))}
          {field('ABHA number', formatAbha(p.abha_number))}
          <Grid size={{ xs: 12, sm: 6, md: 4 }}>
            <Typography variant="caption" color="text.secondary">ABHA address</Typography>
            <Stack direction="row" spacing={1} alignItems="center">
              <Typography>{p.abha_address || '—'}</Typography>
              {p.abha_address && <Chip size="small" color={p.abha_verified ? 'success' : 'default'}
                label={p.abha_verified ? 'Verified' : 'Not verified'} />}
            </Stack>
          </Grid>
          {field('Emergency contact', [p.emergency_contact_name, p.emergency_contact_relation, p.emergency_contact_phone]
            .filter(Boolean).join(' · '))}
        </Grid>
      </Section>

      <Section title="Visits" empty={data.visits.length === 0}>
        <Stack spacing={2}>
          {data.visits.map((v) => (
            <Box key={v.id} sx={{ borderLeft: 3, borderColor: 'primary.main', pl: 2 }}>
              <Typography fontWeight={600}>{formatDateTime(v.visit_at)} · {v.doctor.full_name}</Typography>
              {v.chief_complaint && <Typography><b>Complaint:</b> {v.chief_complaint}</Typography>}
              {v.conditions.length > 0 && (
                <Stack direction="row" spacing={1} sx={{ my: 0.5, flexWrap: 'wrap' }} useFlexGap>
                  {v.conditions.map((c) => <Chip key={c.id} size="small" label={c.code ? `${c.display} (${c.code})` : c.display} />)}
                </Stack>
              )}
              {v.clinical_findings && <Typography><b>Findings:</b> {v.clinical_findings}</Typography>}
              {v.vitals && Object.keys(v.vitals).length > 0 && (
                <Typography variant="body2" color="text.secondary">
                  {Object.entries(v.vitals).map(([k, val]) => `${VITALS[k] ?? k}: ${val}`).join(' · ')}
                </Typography>
              )}
              {v.treatment_plan && <Typography><b>Plan:</b> {v.treatment_plan}</Typography>}
              {(v.follow_up_instructions || v.follow_up_date) && (
                <Typography><b>Follow-up:</b> {[v.follow_up_instructions, v.follow_up_date && formatDate(v.follow_up_date)]
                  .filter(Boolean).join(' · ')}</Typography>
              )}
            </Box>
          ))}
        </Stack>
      </Section>

      <Section title="Prescriptions" empty={data.prescriptions.length === 0}>
        {data.prescriptions.map((rx) => (
          <Box key={rx.id} sx={{ mb: 2, overflowX: 'auto' }}>
            <Typography fontWeight={600}>{formatDate(rx.prescription_date)} · {rx.doctor.full_name}</Typography>
            <Table size="small">
              <TableHead><TableRow>
                <TableCell>Medicine</TableCell><TableCell>Dose</TableCell><TableCell>How often</TableCell>
                <TableCell>Days</TableCell><TableCell>Instructions</TableCell>
              </TableRow></TableHead>
              <TableBody>
                {rx.items.map((i) => (
                  <TableRow key={i.id}>
                    <TableCell>{i.medicine_name}</TableCell><TableCell>{i.dosage} ({i.route})</TableCell>
                    <TableCell>{i.frequency}</TableCell><TableCell>{i.duration_days}</TableCell>
                    <TableCell>{i.instructions}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {rx.notes && <Typography variant="body2" sx={{ mt: 0.5 }}>{rx.notes}</Typography>}
          </Box>
        ))}
      </Section>

      <Section title="Lab reports" empty={data.lab_reports.length === 0}>
        {data.lab_reports.map((r) => (
          <Box key={r.id} sx={{ mb: 2, overflowX: 'auto' }}>
            <Typography fontWeight={600}>{r.test_name} · {formatDate(r.approved_at ?? r.ordered_at)}</Typography>
            <Table size="small">
              <TableHead><TableRow>
                <TableCell>Test</TableCell><TableCell>Result</TableCell><TableCell>Normal range</TableCell><TableCell />
              </TableRow></TableHead>
              <TableBody>
                {r.results.map((x) => (
                  <TableRow key={x.code}>
                    <TableCell>{x.name}</TableCell>
                    <TableCell>{x.value} {x.unit}</TableCell>
                    <TableCell>{x.ref_text ?? [x.ref_low, x.ref_high].filter((n) => n !== null).join(' – ')}</TableCell>
                    <TableCell>
                      {x.interpretation === 'H' && <Chip size="small" color="warning" label="High" />}
                      {x.interpretation === 'L' && <Chip size="small" color="warning" label="Low" />}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {r.conclusion && <Typography variant="body2" sx={{ mt: 0.5 }}><b>Conclusion:</b> {r.conclusion}</Typography>}
          </Box>
        ))}
      </Section>
    </Box>
  )
}
