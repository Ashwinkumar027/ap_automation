<template>
  <div>
    <!-- Top Breadcrumb & Actions -->
    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;">
      <div style="display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--muted);">
        <router-link to="/payment-batches" style="color: var(--purple); text-decoration: none; font-weight: 700;">← Back to Batches</router-link>
        <span>/</span>
        <span>Weekly Accounts Payment Batch</span>
        <span>/</span>
        <strong style="color: var(--ink);">{{ batchId || 'PB-2026-10-W4' }}</strong>
      </div>

      <div style="display: flex; gap: 8px;">
        <button class="primary-btn" style="background: linear-gradient(120deg, #08a96a, #058f58);" @click="downloadIdfcExcel">
          ⇩ Download 15-Col IDFC Bank Excel
        </button>
        <button class="primary-btn" style="padding: 8px 16px; font-size: 11px;" @click="handleBulkDisburse">
          💳 Disburse Batch
        </button>
      </div>
    </div>

    <!-- 4-Step Payout Stepper -->
    <div style="background: rgba(255,255,255,0.9); border: 1px solid #e7e8f8; border-radius: 18px; padding: 14px 18px; margin-bottom: 20px; box-shadow: var(--shadow); overflow-x: auto;">
      <div style="display: flex; align-items: center; justify-content: space-between; min-width: 680px; gap: 8px;">
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

    <!-- KPI Summary Row -->
    <section class="kpis">
      <div class="kpi">
        <div class="kpi-icon purple">▣</div>
        <div>
          <div class="kpi-number">{{ batchItems.length }}</div>
          <div class="kpi-label">Claims in Batch</div>
        </div>
      </div>
      <div class="kpi">
        <div class="kpi-icon amber">₹</div>
        <div>
          <div class="kpi-number">₹ {{ totalGross.toLocaleString('en-IN') }}</div>
          <div class="kpi-label">Gross Amount</div>
        </div>
      </div>
      <div class="kpi">
        <div class="kpi-icon red">✂</div>
        <div>
          <div class="kpi-number">₹ {{ totalTds.toLocaleString('en-IN') }}</div>
          <div class="kpi-label">Statutory TDS Deducted</div>
        </div>
      </div>
      <div class="kpi">
        <div class="kpi-icon green">✓</div>
        <div>
          <div class="kpi-number">₹ {{ totalNetPayable.toLocaleString('en-IN') }}</div>
          <div class="kpi-label">Net Disbursable Payout</div>
        </div>
      </div>
    </section>

    <!-- Consolidated Payout Items Table -->
    <div style="background: rgba(255,255,255,0.92); border: 1px solid #e7e8f8; border-radius: 20px; padding: 22px; box-shadow: var(--shadow);">
      <h3 style="margin: 0 0 16px; font-size: 13px; font-weight: 800; color: #434c6d; text-transform: uppercase;">
        Batch Disbursement Records (15-Column Corporate Banking Format)
      </h3>

      <div style="border: 1px solid #e7e8f8; border-radius: 14px; overflow: hidden;">
        <table style="width: 100%; border-collapse: collapse; font-size: 11px;">
          <thead style="background: #f8f9ff;">
            <tr>
              <th style="padding: 10px 12px;">#</th>
              <th style="padding: 10px 12px;">BENEFICIARY NAME</th>
              <th style="padding: 10px 12px;">ACCOUNT NO.</th>
              <th style="padding: 10px 12px;">IFSC CODE</th>
              <th style="padding: 10px 12px;">CLAIM TYPE</th>
              <th style="padding: 10px 12px;">CLAIM REF</th>
              <th style="padding: 10px 12px;">NET AMOUNT</th>
              <th style="padding: 10px 12px;">UTR NUMBER</th>
              <th style="padding: 10px 12px;">STATUS</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(item, idx) in batchItems" :key="item.ref" style="border-top: 1px solid #f0f1fa;">
              <td style="padding: 8px 12px;">{{ idx + 1 }}</td>
              <td style="padding: 8px 12px;"><strong>{{ item.beneficiary }}</strong></td>
              <td style="padding: 8px 12px;"><code>{{ item.account }}</code></td>
              <td style="padding: 8px 12px;"><code>{{ item.ifsc }}</code></td>
              <td style="padding: 8px 12px;">{{ item.type }}</td>
              <td style="padding: 8px 12px;"><span style="color: var(--purple-dark); font-weight: 700;">{{ item.ref }}</span></td>
              <td style="padding: 8px 12px;" class="amount">₹ {{ item.netAmount.toLocaleString('en-IN') }}</td>
              <td style="padding: 8px 12px;"><code>{{ item.utr || 'Pending Payout' }}</code></td>
              <td style="padding: 8px 12px;">
                <span class="status" :class="item.utr ? 'approved' : 'pending'">{{ item.utr ? 'Paid' : 'Ready' }}</span>
              </td>
            </tr>
          </tbody>
        </table>
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

const batchId = computed(() => route.params.id || 'PB-2026-10-W4');
const currentStep = ref(3);

const steps = [
  { title: 'Consolidated', subtitle: 'Friday 12 PM' },
  { title: 'Director Sanction', subtitle: 'Sanctioned' },
  { title: 'IDFC Payout Excel', subtitle: '15-Col Generated' },
  { title: 'Disbursed', subtitle: 'UTR Stamped' },
];

const batchItems = ref([
  { beneficiary: 'Grand Convention Center & Resort Pvt Ltd', account: '50200088991122', ifsc: 'HDFC0000123', type: 'Vendor Invoice (Lane 3A)', ref: 'VINV-2026-10-0361', netAmount: 240100, gross: 245000, tds: 4900, utr: 'IDFC20261026001' },
  { beneficiary: 'Tech Corp Solutions India Pvt Ltd', account: '91201004556677', ifsc: 'UTIB0000456', type: 'Vendor Invoice (Lane 3A)', ref: 'VINV-2026-10-0360', netAmount: 117000, gross: 130000, tds: 13000, utr: 'IDFC20261026002' },
  { beneficiary: 'Ramesh Kumar', account: '309988776655', ifsc: 'SBIN0001234', type: 'Employee Travel (Lane 2)', ref: 'EC-2026-0045', netAmount: 4200, gross: 4200, tds: 0, utr: 'IDFC20261026003' },
  { beneficiary: 'Receptionist / Front Desk', account: '601122334455', ifsc: 'IDIB0000998', type: 'Petty Cash Imprest (Lane 1)', ref: 'PC-2026-W43-AAG', netAmount: 8450, gross: 8450, tds: 0, utr: 'IDFC20261026004' },
]);

const totalGross = computed(() => batchItems.value.reduce((acc, x) => acc + x.gross, 0));
const totalTds = computed(() => batchItems.value.reduce((acc, x) => acc + x.tds, 0));
const totalNetPayable = computed(() => batchItems.value.reduce((acc, x) => acc + x.netAmount, 0));

function downloadIdfcExcel() {
  const headers = ['Sr No', 'Payment Type', 'Client Reference No', 'Amount', 'Currency', 'Debit Account No', 'Beneficiary Name', 'Beneficiary Account No', 'Beneficiary IFSC', 'Beneficiary Email', 'Remarks', 'Txn Date', 'Payment Mode'];
  const rows = batchItems.value.map((x, idx) => [
    idx + 1, 'VENDOR_PAYOUT', x.ref, x.netAmount, 'INR', '10088991122', x.beneficiary, x.account, x.ifsc, 'accounts@vendor.com', `Settlement ${x.ref}`, '2026-10-26', 'NEFT'
  ]);
  const csv = [headers, ...rows].map(r => r.map(v => `"${String(v).replace(/"/g, '""')}"`).join(',')).join('\r\n');
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = `IDFC_15_Col_Batch_${batchId.value}.csv`;
  a.click();
  URL.revokeObjectURL(url);
  emitToast('15-Column IDFC Bank Excel generated and downloaded.');
}

function handleBulkDisburse() {
  currentStep.value = 4;
  emitToast('Payment batch marked Disbursed with bank UTR timestamps.');
}
</script>

