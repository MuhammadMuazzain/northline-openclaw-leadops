-- Top scored leads ready for outreach queue
SELECT id, business_name, category, metro, phone, email, website_status, score, status
FROM leads
WHERE status IN ('new', 'qualified')
  AND score >= 55
  AND (email IS NOT NULL AND email != '')
ORDER BY score DESC, updated_at DESC
LIMIT 50;

-- Reply / contact funnel
SELECT status, COUNT(*) AS n
FROM leads
GROUP BY status
ORDER BY n DESC;

-- Outreach audit (last 7 days conceptually — filter in app if needed)
SELECT e.id, l.business_name, e.channel, e.status, e.template_id, e.created_at
FROM outreach_events e
JOIN leads l ON l.id = e.lead_id
ORDER BY e.created_at DESC
LIMIT 100;
