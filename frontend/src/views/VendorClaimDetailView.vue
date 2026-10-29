<template>
  <div v-if="claim">
    <!-- Breadcrumb & Top Bar -->
    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;">
      <div style="display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--muted);">
        <router-link to="/vendor-claims" style="color: var(--purple); text-decoration: none; font-weight: 700;">Home</router-link>
        <span>›</span>
        <router-link to="/vendor-claims" style="color: var(--purple); text-decoration: none;">Vendor Invoice Claim</router-link>
        <span>›</span>
        <strong style="color: var(--ink);">{{ claim.id }}</strong>
      </div>

      <div style="display: flex; gap: 8px;">
        <button class="small-btn" @click="emitToast('Generating PDF download...')">⇩ Download PDF</button>
        <button class="small-btn" @click="window.print()">🖨 Print</button>
        <button class="small-btn" @click="emitToast('Share link copied to clipboard.')">↗ Share</button>
        <button class="small-btn" @click="emitToast('More options opened.')">⋮ More</button>
      </div>
    </div>

    <!-- Heading with Status -->
    <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 20px;">
      <router-link to="/vendor-claims" style="width: 32px; height: 32px; border: 1px solid #e7e8f8; border-radius: 10px; background: white; display: grid; place-items: center; color: var(--ink); text-decoration: none; font-size: 16px;">←</router-link>
      <div>
        <div style="display: flex; align-items: center; gap: 10px;">
          <h1 style="margin: 0; font-size: 26px; font-weight: 800; letter-spacing: -0.6px;">{{ claim.id }}</h1>
          <span class="status" :class="claim.status.toLowerCase()">{{ claim.status }}</span>
        </div>
        <div style="font-size: 12px; color: var(--muted); margin-top: 3px;">{{ claim.vendor }}</div>
      </div>
    </div>

    <!-- 4 Top Stat Cards (Exact Replica of Image 5) -->
    <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 20px;">
      <div style="padding: 16px 18px; border: 1px solid #e7e8f8; border-radius: 18px; background: rgba(255,255,255,0.9); box-shadow: var(--shadow); display: flex; align-items: center; gap: 12px;">
        <div class="kpi-icon purple" style="width: 44px; height: 44px; font-size: 20px;">📄</div>
        <div>
          <strong style="display: block; font-size: 18px; color: var(--ink);">₹ {{ claim.amount.toLocaleString('en-IN') }}</strong>
          <small style="color: var(--muted); font-size: 11px;">Invoice Amount</small>
        </div>
      </div>

      <div style="padding: 16px 18px; border: 1px solid #e7e8f8; border-radius: 18px; background: rgba(255,255,255,0.9); box-shadow: var(--shadow); display: flex; align-items: center; gap: 12px;">
        <div class="kpi-icon amber" style="width: 44px; height: 44px; font-size: 20px;">📅</div>
        <div>
          <strong style="display: block; font-size: 15px; color: var(--ink);">{{ claim.date }}</strong>
          <small style="color: var(--muted); font-size: 11px;">Invoice Date</small>
        </div>
      </div>

      <div style="padding: 16px 18px; border: 1px solid #e7e8f8; border-radius: 18px; background: rgba(255,255,255,0.9); box-shadow: var(--shadow); display: flex; align-items: center; gap: 12px;">
        <div class="kpi-icon green" style="width: 44px; height: 44px; font-size: 20px;">✓</div>
        <div>
          <strong style="display: block; font-size: 15px; color: var(--ink);">{{ claim.date }}</strong>
          <small style="color: var(--muted); font-size: 11px;">Approved On</small>
        </div>
      </div>

      <div style="padding: 16px 18px; border: 1px solid #e7e8f8; border-radius: 18px; background: rgba(255,255,255,0.9); box-shadow: var(--shadow); display: flex; align-items: center; gap: 12px;">
        <div class="kpi-icon purple" style="width: 44px; height: 44px; font-size: 20px;">🏢</div>
        <div>
          <strong style="display: block; font-size: 15px; color: var(--purple-dark);">{{ claim.po || 'Direct' }}</strong>
          <small style="color: var(--muted); font-size: 11px;">Linked PO</small>
        </div>
      </div>
    </div>

    <!-- Navigation Tabs -->
    <div style="display: flex; gap: 8px; margin-bottom: 20px; border-bottom: 1px solid #e7e8fa; padding-bottom: 8px;">
      <button
        v-for="t in ['Overview', 'Approval History', 'Attachments', 'Related Documents', 'Comments']"
        :key="t"
        :class="{ active: activeTab === t }"
        class="tab"
        @click="activeTab = t"
      >
        {{ t }}
      </button>
    </div>

    <!-- Bento Grid Section (Split-Screen Embedded PDF Viewer & Details) -->
    <div style="display: grid; grid-template-columns: 1.4fr 1fr; gap: 18px; margin-bottom: 20px;">
      <!-- Left: Invoice Details + Split Screen Embedded PDF Preview Box -->
      <div style="padding: 22px; border: 1px solid #e7e8f8; border-radius: 20px; background: rgba(255,255,255,0.92); box-shadow: var(--shadow);">
        <h3 style="margin: 0 0 16px; font-size: 13px; font-weight: 800; color: #434c6d; display: flex; align-items: center; gap: 8px;">
          <span>📄</span> Invoice Details & Document Preview
        </h3>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 20px;">
          <div>
            <div style="font-size: 11px; margin-bottom: 8px;"><span style="color: var(--muted);">Vendor Name:</span> <strong style="color: var(--ink);">{{ claim.vendor }}</strong></div>
            <div style="font-size: 11px; margin-bottom: 8px;"><span style="color: var(--muted);">Invoice Number:</span> <strong style="color: var(--ink);">{{ claim.invoice }}</strong></div>
            <div style="font-size: 11px; margin-bottom: 8px;"><span style="color: var(--muted);">Invoice Date:</span> <strong style="color: var(--ink);">{{ claim.date }}</strong></div>
            <div style="font-size: 11px; margin-bottom: 8px;"><span style="color: var(--muted);">Due Date:</span> <strong style="color: var(--ink);">09-11-2026</strong></div>
            <div style="font-size: 11px; margin-bottom: 8px;"><span style="color: var(--muted);">Tax Amount:</span> <strong style="color: var(--ink);">₹ 44,100</strong></div>
            <div style="font-size: 11px; margin-bottom: 8px;"><span style="color: var(--muted);">Total Amount:</span> <strong style="color: var(--purple-dark); font-size: 13px;">₹ {{ claim.amount.toLocaleString('en-IN') }}</strong></div>
          </div>

          <!-- Embedded PDF Preview Window -->
          <div style="border: 1px solid #e2e4f5; border-radius: 14px; padding: 12px; background: #fbfcff; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; min-height: 170px;">
            <div style="font-size: 32px; color: var(--purple); margin-bottom: 6px;">📑</div>
            <strong style="font-size: 11px; color: var(--ink);">{{ claim.invoice }}.pdf</strong>
            <small style="color: var(--muted); font-size: 9px; margin-bottom: 12px;">Verified Original Bill Attached (245 KB)</small>
            <button class="small-btn" style="border-color: #c8baff; color: var(--purple);" @click="emitToast('Previewing full tax invoice document in modal.')">
              View Full PDF ↗
            </button>
          </div>
        </div>

        <!-- Line Items Table -->
        <h4 style="margin: 0 0 10px; font-size: 12px; font-weight: 800; color: #434c6d;">Line Items Breakdown</h4>
        <div style="border: 1px solid #e7e8f8; border-radius: 12px; overflow: hidden;">
          <table style="width: 100%; border-collapse: collapse; font-size: 11px;">
            <thead style="background: #f8f9ff;">
              <tr>
                <th style="padding: 8px 10px;">#</th>
                <th style="padding: 8px 10px;">DESCRIPTION</th>
                <th style="padding: 8px 10px;">QTY</th>
                <th style="padding: 8px 10px;">RATE</th>
                <th style="padding: 8px 10px;">AMOUNT</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td style="padding: 8px 10px;">1</td>
                <td style="padding: 8px 10px;">Conference Hall Rental & Audio Setup</td>
                <td style="padding: 8px 10px;">1</td>
                <td style="padding: 8px 10px;">₹ 1,50,000</td>
                <td style="padding: 8px 10px; font-weight: 700;">₹ 1,50,000</td>
              </tr>
              <tr style="border-top: 1px solid #f0f1fa;">
                <td style="padding: 8px 10px;">2</td>
                <td style="padding: 8px 10px;">Catering Services (Lunch & High Tea)</td>
                <td style="padding: 8px 10px;">1</td>
                <td style="padding: 8px 10px;">₹ 75,000</td>
                <td style="padding: 8px 10px; font-weight: 700;">₹ 75,000</td>
              </tr>
              <tr style="border-top: 1px solid #f0f1fa;">
                <td style="padding: 8px 10px;">3</td>
                <td style="padding: 8px 10px;">Decoration & Stage Lighting</td>
                <td style="padding: 8px 10px;">1</td>
                <td style="padding: 8px 10px;">₹ 20,000</td>
                <td style="padding: 8px 10px; font-weight: 700;">₹ 20,000</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Right: Approval Workflow + Quick Actions -->
      <div style="display: flex; flex-direction: column; gap: 16px;">
        <!-- Approval Workflow Vertical Stepper (Exact Replica of Image 5) -->
        <div style="padding: 22px; border: 1px solid #e7e8f8; border-radius: 20px; background: rgba(255,255,255,0.92); box-shadow: var(--shadow);">
          <h3 style="margin: 0 0 16px; font-size: 13px; font-weight: 800; color: #434c6d; display: flex; align-items: center; gap: 8px;">
            <span>🛡</span> Approval Workflow
          </h3>

          <div style="display: flex; flex-direction: column; gap: 14px; position: relative;">
            <div v-for="w in workflowSteps" :key="w.title" style="display: flex; align-items: flex-start; gap: 12px;">
              <div
                :style="{
                  width: '24px',
                  height: '24px',
                  borderRadius: '50%',
                  display: 'grid',
                  placeItems: 'center',
                  fontSize: '11px',
                  fontWeight: '800',
                  background: w.done ? '#08a96a' : '#d4d8ee',
                  color: 'white',
                  flexShrink: 0
                }"
              >
                {{ w.done ? '✓' : '•' }}
              </div>
              <div style="flex: 1;">
                <div style="display: flex; justify-content: space-between;">
                  <strong style="font-size: 11px; color: var(--ink);">{{ w.title }}</strong>
                  <span style="font-size: 10px; font-weight: 700; color: #08a96a;" v-if="w.done">Completed</span>
                </div>
                <small style="color: var(--muted); font-size: 10px; display: block; margin-top: 2px;">{{ w.time }}</small>
              </div>
            </div>
          </div>
        </div>

        <!-- Quick Actions Drawer -->
        <div style="padding: 20px; border: 1px solid #e7e8f8; border-radius: 20px; background: rgba(255,255,255,0.92); box-shadow: var(--shadow);">
          <h4 style="margin: 0 0 12px; font-size: 12px; font-weight: 800; color: #434c6d;">Quick Actions</h4>
          <div style="display: flex; flex-direction: column; gap: 8px;">
            <button class="primary-btn" style="width: 100%; justify-content: center;" @click="emitToast('Create payment batch instruction triggered.')">
              💳 Create Payment Batch
            </button>
            <button class="secondary-btn" style="width: 100%; justify-content: center; color: #dc3b4a;" @click="emitToast('Invoice marked Disputed.')">
              ✕ Reject / Dispute Invoice
            </button>
            <button class="secondary-btn" style="width: 100%; justify-content: center;" @click="emitToast('Clarification request sent to vendor.')">
              ✉ Request Clarification
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

const activeTab = ref('Overview');

const claim = computed(() => {
  const id = route.params.id || 'VINV-2026-10-0361';
  return {
    id,
    invoice: 'GC-INV-2026-001',
    vendor: 'Grand Convention Center & Resort',
    date: '26-10-2026',
    amount: 245000,
    po: 'PO-2026-001',
    status: 'Approved',
  };
});

const workflowSteps = [
  { title: 'Submitted by Ashwin Kumar', time: '26 Oct 2026 10:15 AM', done: true },
  { title: 'Approved by Manager (Priya Menon)', time: '26 Oct 2026 11:20 AM', done: true },
  { title: 'Approved by Finance Team', time: '26 Oct 2026 12:05 PM', done: true },
  { title: 'Final Approved (Accounts Director)', time: '26 Oct 2026 12:10 PM', done: true },
];
</script>

