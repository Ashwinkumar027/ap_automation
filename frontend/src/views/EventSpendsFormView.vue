<template>
  <div>
    <!-- Top Breadcrumb & Actions -->
    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;">
      <div style="display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--muted);">
        <router-link to="/event-spends" style="color: var(--purple); text-decoration: none; font-weight: 700;">← Back to Event Spends</router-link>
        <span>/</span>
        <span>Corporate Events Hub</span>
        <span>/</span>
        <strong style="color: var(--ink);">{{ eventId || 'New Event Master' }}</strong>
      </div>

      <div style="display: flex; gap: 8px;">
        <button class="small-btn" @click="emitToast('Audit report for event downloaded.')">⇩ Export Event Audit</button>
        <button class="primary-btn" style="padding: 8px 16px; font-size: 11px;" @click="handleSave">Save Event</button>
      </div>
    </div>

    <!-- 5-Step Event Lifecycle Stepper -->
    <div style="background: rgba(255,255,255,0.9); border: 1px solid #e7e8f8; border-radius: 18px; padding: 14px 18px; margin-bottom: 20px; box-shadow: var(--shadow); overflow-x: auto;">
      <div style="display: flex; align-items: center; justify-content: space-between; min-width: 720px; gap: 8px;">
        <div v-for="(step, idx) in steps" :key="step.title" style="display: flex; align-items: center; gap: 10px; flex: 1; padding: 8px 12px; border-radius: 12px; background: currentStep >= idx + 1 ? '#eee9ff' : 'transparent'; border: currentStep === idx + 1 ? '1px solid #d4c8ff' : 'none';">
          <div
            :style="{
              width: '26px',
              height: '26px',
              borderRadius: '50%',
              display: 'grid',
              placeItems: 'center',
              fontSize: '11px',
              fontWeight: '800',
              background: currentStep >= idx + 1 ? 'linear-gradient(135deg, #704cff, #542ff0)' : '#f0f1fa',
              color: currentStep >= idx + 1 ? 'white' : '#7b83a3',
            }"
          >
            {{ idx + 1 }}
          </div>
          <div>
            <div style="font-size: 11px; font-weight: 800; color: var(--ink);">{{ step.title }}</div>
            <div style="font-size: 9px; color: var(--muted);">{{ step.subtitle }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Live Budget Progress Ribbon (PRD Section 7 Engine) -->
    <div style="padding: 20px; border: 1px solid #e7e8f8; border-radius: 20px; background: rgba(255,255,255,0.92); box-shadow: var(--shadow); margin-bottom: 20px;">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px;">
        <div>
          <span class="eyebrow" style="margin-bottom: 4px;">CONCURRENCY-SHIELDED LIVE LEDGER</span>
          <h2 style="margin: 0; font-size: 20px; font-weight: 800;">{{ eventData.name }}</h2>
        </div>
        <span class="status" :class="eventData.utilPct > 100 ? 'disputed' : eventData.utilPct > 80 ? 'pending' : 'approved'">
          {{ eventData.utilPct > 100 ? 'OVERRUN ALERT (>100%)' : eventData.utilPct > 80 ? 'APPROACHING LIMIT (80-100%)' : 'WITHIN BUDGET' }}
        </span>
      </div>

      <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 16px;">
        <div style="padding: 12px 14px; background: #faf9ff; border: 1px solid #ece7ff; border-radius: 12px;">
          <small style="color: var(--muted); font-size: 10px;">Allocated Budget</small>
          <strong style="display: block; font-size: 16px; color: var(--ink);">₹ {{ eventData.budget.toLocaleString('en-IN') }}</strong>
        </div>
        <div style="padding: 12px 14px; background: #faf9ff; border: 1px solid #ece7ff; border-radius: 12px;">
          <small style="color: var(--muted); font-size: 10px;">Stream A (Direct POs)</small>
          <strong style="display: block; font-size: 16px; color: #2685f6;">₹ {{ eventData.streamA.toLocaleString('en-IN') }}</strong>
        </div>
        <div style="padding: 12px 14px; background: #faf9ff; border: 1px solid #ece7ff; border-radius: 12px;">
          <small style="color: var(--muted); font-size: 10px;">Stream B (Ground Advance)</small>
          <strong style="display: block; font-size: 16px; color: #d98a00;">₹ {{ eventData.streamB.toLocaleString('en-IN') }}</strong>
        </div>
        <div style="padding: 12px 14px; background: #faf9ff; border: 1px solid #ece7ff; border-radius: 12px;">
          <small style="color: var(--muted); font-size: 10px;">Remaining Budget</small>
          <strong style="display: block; font-size: 16px; color: #08a96a;">₹ {{ (eventData.budget - eventData.committed).toLocaleString('en-IN') }}</strong>
        </div>
      </div>

      <div>
        <div style="display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 6px;">
          <span>Total Committed Spend Formula: <code>Stream A + max(Advance, SPOC Actuals)</code></span>
          <strong style="color: var(--purple-dark)">{{ eventData.utilPct }}% Budget Utilized</strong>
        </div>
        <div class="progress" :class="{ disputed: eventData.utilPct > 80 }">
          <span :style="{ width: `${Math.min(eventData.utilPct, 100)}%` }"></span>
        </div>
      </div>
    </div>

    <!-- Settlement Delta Math Engine (PRD Section 7, Step 5) -->
    <div style="padding: 22px; border: 1px solid #e7e8f8; border-radius: 20px; background: rgba(255,255,255,0.92); box-shadow: var(--shadow);">
      <h3 style="margin: 0 0 16px; font-size: 13px; font-weight: 800; color: #434c6d; text-transform: uppercase;">
        Event Post-Event Settlement Delta Math
      </h3>

      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
        <div class="detail-list">
          <div class="detail">
            <small>Disbursed Advance (Stream B)</small>
            <strong class="amount">₹ {{ eventData.streamB.toLocaleString('en-IN') }}</strong>
          </div>
          <div class="detail">
            <small>SPOC Actual Ground Spends</small>
            <strong class="amount">₹ {{ eventData.spocActuals.toLocaleString('en-IN') }}</strong>
          </div>
          <div class="detail">
            <small>Settlement Delta Formula</small>
            <strong>SPOC Actuals - Disbursed Advance</strong>
          </div>
          <div class="detail">
            <small>Delta Settlement Case</small>
            <span class="status" :class="settlementDelta >= 0 ? 'approved' : 'pending'">
              {{ settlementDelta > 0 ? 'PAYABLE_TO_SPOC' : settlementDelta < 0 ? 'REFUND_FROM_SPOC' : 'ZERO_BALANCE_BALANCED' }}
            </span>
          </div>
        </div>

        <div style="padding: 16px; background: #faf9ff; border: 1px solid #e7e0ff; border-radius: 14px; display: flex; flex-direction: column; justify-content: space-between;">
          <div v-if="settlementDelta < 0">
            <strong style="color: #bf7b00; font-size: 12px; display: block; margin-bottom: 4px;">
              Unspent Cash Return Required (Mandatory Bank UTR Reference)
            </strong>
            <p style="margin: 0 0 10px; font-size: 10px; color: var(--muted);">
              SPOC must return unspent funds to company bank account before formal event closure.
            </p>
            <input v-model="refundUtr" placeholder="Enter Bank Return UTR (e.g. UTR-RET-99881)" style="width: 100%; padding: 8px 10px; border: 1px solid #d4c8ff; border-radius: 8px; font-size: 11px;" />
          </div>

          <div v-else>
            <strong style="color: #08a96a; font-size: 12px; display: block; margin-bottom: 4px;">
              Reimbursement Payable to SPOC
            </strong>
            <p style="margin: 0; font-size: 10px; color: var(--muted);">
              SPOC spent out-of-pocket beyond advance. Remainder added to Friday Accounts Batch.
            </p>
          </div>

          <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 14px; padding-top: 12px; border-top: 1px solid #ece7ff;">
            <div>
              <small style="color: var(--muted); font-size: 10px;">Net Settlement Delta</small>
              <div style="font-size: 20px; font-weight: 800; color: var(--purple-dark);">
                ₹ {{ Math.abs(settlementDelta).toLocaleString('en-IN') }}
              </div>
            </div>
            <button class="primary-btn" style="padding: 8px 16px; font-size: 11px;" @click="handleEventClosure">
              ✓ Finalize & Close Event
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue';
import { useRoute } from 'vue-router';

const route = useRoute();
const emit = defineEmits(['toast']);
function emitToast(msg) { emit('toast', msg); }

const eventId = computed(() => route.params.id || 'EVT-2026-001');
const currentStep = ref(3);
const refundUtr = ref('');

const steps = [
  { title: 'Budget Allocation', subtitle: 'Event Master' },
  { title: 'Advance Disbursed', subtitle: 'IDFC Payout' },
  { title: 'Ground Spends', subtitle: 'Live Stream B' },
  { title: 'Accounts Audit', subtitle: 'Receipt Verification' },
  { title: 'Delta Closure', subtitle: 'Formal Settlement' },
];

const eventData = ref({
  id: eventId.value,
  name: 'Annual Tech Summit 2026',
  budget: 500000,
  streamA: 245000,
  streamB: 100000,
  spocActuals: 98500,
  committed: 345000,
  utilPct: 69.0,
});

const settlementDelta = computed(() => {
  return eventData.value.spocActuals - eventData.value.streamB;
});

function handleSave() {
  emitToast('Event Master ledger updated.');
}

function handleEventClosure() {
  if (settlementDelta.value < 0 && !refundUtr.value.trim()) {
    alert('Mandatory Security Rule: Please provide the unspent cash return Bank UTR reference before event closure.');
    return;
  }
  emitToast('Event Master settled and formally closed in accounts ledger.');
}
</script>

