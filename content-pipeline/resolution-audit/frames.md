# Leak Frames

Use this file after choosing a tag from `leak-index.md`. Each section gives
safe language for content, report labels, and picture prompts.

## `repeat_resolution` - Repeat Resolution Spend

Safe report label:

- Repeat Resolution Spend

Safe language:

- "The same resolved outcome may be getting paid for again and again."
- "This is estimated exposure from repeated AI-resolved questions, not promised
  savings."
- "The audit should compare repeated questions against AI-resolution and reopen
  markers before calling the spend preventable."

Unsafe language:

- "Your AI vendor is overcharging you."
- "Every repeated AI resolution is wasted money."
- "This will cut your AI bill."

Social angle:

- "If an AI agent resolves the same question 300 times, is that success, or a
  metered symptom?"

Visual direction:

- A receipt with the same support question appearing as repeated line items,
  each marked "resolved?" with a small evidence icon.

Fallback:

- If AI-resolution data is missing, say "vendor-meter risk" and do not estimate
  dollars.

## `ai_attempt_waste` - Paid Attempts vs Resolutions

Safe report label:

- Paid Attempts vs Resolutions

Safe language:

- "This leak compares paid AI attempts or sessions against proven resolutions."
- "A paid attempt is not automatically waste. It becomes interesting when it
  clusters around unresolved, escalated, or repeated questions."
- "The audit needs session outcomes before estimating exposure."

Unsafe language:

- "All unresolved AI sessions are wasted."
- "Freshdesk charges for failures."
- "This proves the bot is failing."

Social angle:

- "I care less about how many AI sessions ran and more about how many ended the
  customer's problem."

Visual direction:

- A funnel showing paid AI sessions entering at the top, with lanes for
  resolved, escalated, repeated, and unknown.

Fallback:

- If outcome labels are missing, report session-meter exposure only.

## `ticket_overage` - Preventable Overage Cost

Safe report label:

- Preventable Overage Cost

Safe language:

- "Repeat tickets may be contributing to plan-limit pressure."
- "Overage exposure requires the customer's plan allowance, actual billed
  volume, and repeat-ticket volume."
- "The audit can identify repeat demand that is worth reviewing before it
  pushes a team into a higher tier."

Unsafe language:

- "These tickets caused your overage."
- "You can avoid your next plan upgrade."
- "This volume is definitely preventable."

Social angle:

- "Some support teams do not just pay for repeats in labor. They pay for them
  again when the repeats push usage above plan limits."

Visual direction:

- A plan-limit gauge where repeat tickets are highlighted as a separate color
  inside the volume bar.

Fallback:

- If plan allowance is unknown, call this a plan-limit risk and skip dollars.

## `seat_pressure` - Avoidable Seat Pressure

Safe report label:

- Avoidable Seat Pressure

Safe language:

- "Repeat demand can contribute to agent-seat pressure."
- "This is a workload signal, not proof that a hire or seat can be avoided."
- "The audit should translate repeats into reviewable workload before making
  staffing claims."

Unsafe language:

- "This prevents a support hire."
- "Cancel these seats."
- "The audit proves your team is overstaffed."

Social angle:

- "Before a team debates another seat, I want to know which repeated questions
  are creating the pressure."

Visual direction:

- A staffing board where repeated-question cards are stacked next to agent-seat
  slots, with a question mark over the staffing threshold.

Fallback:

- If staffing thresholds are missing, report workload pressure only.

## `qa_waste` - QA Waste on Preventable

Safe report label:

- QA Waste on Preventable

Safe language:

- "QA review may be scoring interactions that exist because the same issue keeps
  repeating."
- "This leak is about QA review surface, not a claim that QA work is useless."
- "A repeat is only preventable after the audit shows a credible fix path."

Unsafe language:

- "QA is wasting time."
- "Stop scoring these tickets."
- "Every scored repeat is wasted QA spend."

Social angle:

- "If QA keeps reviewing the same avoidable interaction, the useful question may
  be upstream: why does the interaction keep happening?"

Visual direction:

- A QA scorecard over repeated ticket cards, with a separate lane titled
  "upstream fix review."

Fallback:

- If QA scope is unknown, label the leak as possible QA review surface.

## `wfm_forecast` - Forecast Pollution

Safe report label:

- Forecast Pollution

Safe language:

- "Repeat demand may inflate the volume used for staffing forecasts."
- "The audit can separate recurring demand from new demand before the team
  treats all volume as inevitable."
- "Forecast impact requires WFM inputs and a reviewable removable-repeat
  hypothesis."

Unsafe language:

- "Your forecast is wrong."
- "Remove these tickets from staffing."
- "This proves you need fewer agents."

Social angle:

- "If the forecast treats every repeat as inevitable, the staffing model may be
  absorbing problems another team should fix."

Visual direction:

- A forecast chart with total volume in gray and repeated-question demand
  highlighted as an investigatory overlay.

Fallback:

- If WFM data is missing, say forecast impact is unmeasured.

## `channel_tax` - Multi-Channel Repeat Demand

Safe report label:

- Multi-Channel Repeat Demand

Safe language:

- "The same unresolved question can generate demand across paid channels."
- "Channel tax requires channel mix and pricing inputs."
- "The audit should show where repeats appear: chat, email, SMS, WhatsApp,
  phone, or another support surface."

Unsafe language:

- "Turn off this channel."
- "All SMS repeats are waste."
- "This channel is causing the problem."

Social angle:

- "A repeat that starts in chat and comes back through SMS or phone is not just
  a content problem. It is a channel-cost problem."

Visual direction:

- One repeated question branching into channel lanes, with small cost markers
  on each lane.

Fallback:

- If channel data is missing, report repeat demand without channel-cost
  exposure.

## `knowledge_gap` - Knowledge Gap Cost

Safe report label:

- Knowledge Gap Cost

Safe language:

- "This is a candidate knowledge gap, not proof that documentation caused the
  repeat."
- "The audit should ask whether the answer is missing, buried, contradicted, or
  blocked by a product/policy/process issue."
- "A knowledge gap can produce a draft answer only when ticket evidence supports
  one."

Unsafe language:

- "Your help center failed."
- "Just write an FAQ."
- "The KB is the reason customers contacted support."

Social angle:

- "The dangerous reflex is turning every repeated question into a help article.
  Sometimes the right answer is 'do not write yet; fix the workflow.'"

Visual direction:

- A map with four paths from a repeated question: missing answer, buried answer,
  contradictory answer, and no proven answer.

Fallback:

- If KB/source evidence is missing, mark as needs content/source review.

## `macro_debt` - Macro Debt

Safe report label:

- Macro Debt

Safe language:

- "Agents may be rewriting the same answer because no approved macro or draft
  exists."
- "Macro debt is audit-only. It depends on repeated wording, handle-time
  samples, or source-ticket evidence."
- "The output can be a review-ready draft when the ticket history contains
  scoped resolution evidence."

Unsafe language:

- "Agents are wasting time."
- "The macro will solve the issue."
- "This answer is approved."

Social angle:

- "Sometimes the cheapest leak is not the platform bill. It is the same answer
  being rewritten in slightly different words all week."

Visual direction:

- Several agent reply drafts converging into one review-ready answer card, with
  source-ticket markers underneath.

Fallback:

- If repeated wording is missing, do not estimate. Ask for more ticket evidence.

## `false_deflection` - False Deflection

Safe report label:

- False Deflection Candidate

Safe language:

- "Deflected does not always mean resolved."
- "This tag needs follow-up contact, reopen, repeated-question, or negative-CSAT
  evidence before it becomes a finding."
- "The audit should treat bot closures as candidates for review, not accusations."

Unsafe language:

- "The bot lied."
- "Your deflection numbers are fake."
- "Every reopened AI ticket is false deflection."

Social angle:

- "If the bot closes the conversation and the customer comes back with the same
  question, what metric catches that?"

Visual direction:

- A loop where a bot-closed conversation returns to the support queue with the
  same question, labeled "review candidate" rather than "failure."

Fallback:

- If reopen/follow-up data is missing, say "deflection quality cannot be
  judged from closure alone."
