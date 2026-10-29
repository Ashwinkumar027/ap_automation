<template>
  <div>
    <!-- Top Breadcrumb & Actions -->
    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;">
      <div style="display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--muted);">
        <router-link to="/petty-cash" style="color: var(--purple); text-decoration: none; font-weight: 700;">← Back to Petty Cash</router-link>
        <span>/</span>
        <span>Petty Cash Entry</span>
        <span>/</span>
        <strong style="color: var(--ink);">{{ voucherId || 'New Petty Cash Entry' }}</strong>
        <span v-if="!isSaved" style="background: #fff3d7; color: #bf7b00; font-size: 10px; font-weight: 800; padding: 2px 7px; border-radius: 6px;">Not Saved</span>
      </div>

      <div style="display: flex; align-items: center; gap: 14px;">
        <div style="text-align: right;">
          <small style="color: var(--muted); font-size: 10px; text-transform: uppercase; font-weight: 700;">Total Amount</small>
          <div style="font-size: 20px; font-weight: 800; color: var(--purple-dark);">
            ₹ {{ totalVoucherAmount.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }}
          </div>
        </div>
        <router-link to="/petty-cash" class="secondary-btn" style="text-decoration: none; padding: 8px 14px; font-size: 11px;">Cancel</router-link>
        <button class="primary-btn" style="padding: 8px 18px; font-size: 11px;" @click="handleSave">Save</button>
      </div>
    </div>

    <!-- 6-Step Approval Workflow Stepper (Matching Screenshot 14) -->
    <div style="background: rgba(255,255,255,0.92); border: 1px solid #e7e8f8; border-radius: 18px; padding: 14px 18px; margin-bottom: 20px; box-shadow: var(--shadow); overflow-x: auto;">
      <div style="display: flex; align-items: center; justify-content: space-between; min-width: 720px; gap: 8px;">
        <div
          v-for="(step, idx) in steps"
          :key="step.title"
          :style="{
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            flex: '1',
            padding: '8px 12px',
            borderRadius: '12px',
            background: currentStep === idx + 1 ? '#eee9ff' : 'transparent',
            border: currentStep === idx + 1 ? '1px solid #d4c8ff' : '1px solid transparent',
            transition: '0.2s'
          }"
        >
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
              boxShadow: currentStep === idx + 1 ? '0 0 0 3px #dfd7ff' : 'none',
              flexShrink: '0'
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

    <!-- Main Form Container -->
    <div style="background: rgba(255,255,255,0.92); border: 1px solid #e7e8f8; border-radius: 20px; padding: 24px; box-shadow: var(--shadow);">
      <!-- Header -->
      <h3 style="margin: 0 0 16px; font-size: 13px; font-weight: 800; color: #434c6d; text-transform: uppercase; letter-spacing: 0.5px;">
        Petty Cash Claim Header
      </h3>

      <div class="form-grid" style="margin-bottom: 24px;">
        <div class="field">
          <label>Posting Date *</label>
          <input v-model="formData.postingDate" type="date" @change="recalculateWeekTitle" />
        </div>
        <div class="field">
          <label>Status</label>
          <input :value="formData.status" disabled style="background: #f7f8fc; font-weight: 700; color: #d98a00;" />
        </div>
        <div class="field full">
          <label>Claim Title (Auto: Week # - Company)</label>
          <input :value="formData.claimTitle" disabled style="background: #f7f8fc; font-weight: 700; color: var(--purple-dark);" />
          <small style="color: var(--muted); font-size: 10px; margin-top: 3px; display: block;">
            Automatically calculated from Posting Date week & Company (e.g. "Week 44 - TC").
          </small>
        </div>
        <div class="field">
          <label>Company *</label>
          <select v-model="formData.company" @change="recalculateWeekTitle">
            <option>Anshul A Gupta & Associates</option>
            <option>Quanticus Software Solutions Private Limited</option>
            <option>TestCompany</option>
          </select>
        </div>
        <div class="field">
          <label>Beneficiary Employee (Admin Head / Custodian) *</label>
          <select v-model="formData.custodian">
            <option v-for="emp in employeeOptions" :key="emp.name" :value="emp.name">
              {{ emp.employee_name }} ({{ emp.name }})
            </option>
            <option v-if="!employeeOptions.length" value="Receptionist / Front Desk (Chennai HQ)">Receptionist / Front Desk (Chennai HQ)</option>
            <option v-if="!employeeOptions.length" value="Office Admin (Bangalore Tech Park)">Office Admin (Bangalore Tech Park)</option>
          </select>
        </div>
      </div>

      <!-- Expense Lines (Excel-Style Smart Grid) -->
      <div style="border-top: 1px solid #edf0fa; padding-top: 20px; margin-top: 10px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
          <div>
            <h4 style="margin: 0; font-size: 13px; font-weight: 800; color: var(--ink);">
              Expense Lines [Excel-Style Smart Grid]
            </h4>
            <p style="margin: 3px 0 0; font-size: 11px; color: var(--muted);">
              Add branch expense lines, enter amounts, and attach receipt photos via Add Photo.
            </p>
          </div>
          <button type="button" class="primary-btn" style="padding: 7px 13px; font-size: 11px;" @click="addLine">
            ＋ Add Row
          </button>
        </div>

        <div style="overflow-x: auto; margin-bottom: 16px; border: 1px solid #e7e9fa; border-radius: 14px; background: #ffffff;">
          <table class="grid-table">
            <thead>
              <tr>
                <th style="width: 38px; text-align: center;">#</th>
                <th style="width: 130px;">DATE *</th>
                <th style="width: 170px;">EXPENSE TYPE *</th>
                <th style="min-width: 160px;">SHOP / MERCHANT</th>
                <th style="width: 60px; text-align: center;">GST?</th>
                <th style="width: 140px;">BILL # / TXN ID</th>
                <th style="width: 130px;">AMOUNT (₹) *</th>
                <th style="width: 130px;">RECEIPT</th>
                <th style="min-width: 130px;">SPENT BY</th>
                <th style="width: 45px; text-align: center;">ACTION</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(line, idx) in lines" :key="idx">
                <td style="text-align: center; font-weight: 800; color: var(--muted);">{{ idx + 1 }}</td>
                <td>
                  <input type="date" v-model="line.date" class="grid-input" />
                </td>
                <td>
                  <select v-model="line.type" class="grid-select">
                    <option>Tea & Refreshments</option>
                    <option>Office Supplies & Stationery</option>
                    <option>Courier & Logistics</option>
                    <option>Local Conveyance</option>
                    <option>Cleaning & Pantry</option>
                    <option>Minor Repairs & Hardware</option>
                    <option>Staff Welfare</option>
                    <option>Other Branch Expense</option>
                  </select>
                </td>
                <td>
                  <input v-model="line.merchant" placeholder="Store / Merchant name" class="grid-input" />
                </td>
                <td style="text-align: center;">
                  <input type="checkbox" v-model="line.hasGst" class="grid-check" />
                </td>
                <td>
                  <input v-model="line.billNo" placeholder="Bill or UPI Ref #" class="grid-input" />
                </td>
                <td>
                  <input
                    v-model.number="line.amount"
                    type="number"
                    step="0.01"
                    placeholder="0.00"
                    class="grid-input"
                    style="font-weight: 700; color: var(--ink); text-align: right;"
                  />
                </td>
                <td>
                  <input
                    type="file"
                    :id="`file-input-${idx}`"
                    style="display: none;"
                    @change="handleFileUpload($event, idx)"
                  />
                  <div v-if="line.receiptName" class="receipt-attached-pill">
                    <span>📎 {{ line.receiptName }}</span>
                    <button type="button" @click="line.receiptName = ''" style="border:0;background:transparent;cursor:pointer;color:#e43f50;font-weight:bold;margin-left:4px;">✕</button>
                  </div>
                  <button
                    v-else
                    type="button"
                    class="receipt-upload-btn"
                    @click="triggerFileInput(idx)"
                  >
                    📷 Add Photo
                  </button>
                </td>
                <td>
                  <input v-model="line.spentBy" placeholder="Staff Name" class="grid-input" />
                </td>
                <td style="text-align: center;">
                  <button type="button" class="delete-row-btn" @click="removeLine(idx)" title="Delete Row">
                    ✕
                  </button>
                </td>
              </tr>
              <tr v-if="!lines.length">
                <td colspan="10" style="text-align: center; padding: 24px; color: var(--muted);">
                  No expense lines added yet. Click <strong>+ Add Row</strong> to record an expense.
                </td>
              </tr>
            </tbody>
            <tfoot v-if="lines.length" style="background: #fafaff; border-top: 2px solid #e7e9fa; font-weight: 800;">
              <tr>
                <td colspan="6" style="text-align: right; padding: 10px 14px; color: var(--muted); text-transform: uppercase; font-size: 10px;">
                  Grand Total
                </td>
                <td style="text-align: right; padding: 10px 8px; font-size: 13px; color: var(--purple-dark);">
                  ₹ {{ totalVoucherAmount.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }}
                </td>
                <td colspan="3"></td>
              </tr>
            </tfoot>
          </table>
        </div>

        <div style="display: flex; gap: 8px; margin-bottom: 22px;">
          <button type="button" class="small-btn" @click="addLine">＋ Add row</button>
          <button type="button" class="small-btn" @click="duplicateLastLine" v-if="lines.length">⎘ Duplicate Last Row</button>
        </div>

        <!-- Status & Workflow Summary -->
        <div style="border-top: 1px solid #edf0fa; padding-top: 18px; display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
          <div>
            <div class="field" style="margin-bottom: 12px;">
              <label>Current Approval Level</label>
              <input value="1" disabled style="background: #fcfcff; font-weight: 700;" />
            </div>
            <div class="field">
              <label>Workflow State</label>
              <input value="Draft" disabled style="background: #fcfcff; font-weight: 700; color: #d98a00;" />
            </div>
          </div>

          <div style="display: flex; flex-direction: column; justify-content: flex-end;">
            <label style="display: flex; align-items: center; gap: 8px; font-size: 11px; cursor: pointer; color: var(--muted); margin-bottom: 14px;">
              <input type="checkbox" v-model="formData.isParkedDisputed" class="grid-check" /> Is Parked Disputed Voucher
            </label>
            <div style="display: flex; gap: 8px;">
              <button class="primary-btn" style="flex: 1;" @click="handleSubmitL1">Submit for Admin L1 Review →</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { frappeGetDocList } from '../utils/api';

const route = useRoute();
const router = useRouter();
const emit = defineEmits(['toast']);
function emitToast(msg) { emit('toast', msg); }

const voucherId = computed(() => route.params.id || '');
const isSaved = ref(false);
const currentStep = ref(1);
const employeeOptions = ref([]);

const steps = [
  { title: 'Bill Entry', subtitle: 'Front Desk' },
  { title: 'Admin L1', subtitle: 'Lead Review' },
  { title: 'Admin L2', subtitle: 'Head Sign-off' },
  { title: 'Accounts', subtitle: 'L1 Audit' },
  { title: 'Director', subtitle: 'If Overdue' },
  { title: 'Paid', subtitle: 'Bank UTR' },
];

const formData = ref({
  postingDate: '2026-10-29',
  status: 'Draft',
  claimTitle: 'Week 44 - TC',
  company: 'TestCompany',
  custodian: 'Receptionist / Front Desk (Chennai HQ)',
  isParkedDisputed: false,
});

onMounted(async () => {
  try {
    const emps = await frappeGetDocList('Employee', {
      fields: ['name', 'employee_name', 'department', 'company'],
      limit: 100,
    });
    if (emps && emps.length) {
      employeeOptions.value = emps;
      if (!formData.value.custodian && emps[0]) {
        formData.value.custodian = emps[0].name;
      }
    }
  } catch (e) {
    console.warn('Could not load employees:', e);
  }

  recalculateWeekTitle();
});

function recalculateWeekTitle() {
  const d = new Date(formData.value.postingDate);
  const oneJan = new Date(d.getFullYear(), 0, 1);
  const numberOfDays = Math.floor((d - oneJan) / (24 * 60 * 60 * 1000));
  const weekNumber = Math.ceil((d.getDay() + 1 + numberOfDays) / 7);
  const compAbbr = formData.value.company.split(' ').map(x => x[0]).join('').toUpperCase().slice(0, 3) || 'TC';
  formData.value.claimTitle = `Week ${weekNumber} - ${compAbbr}`;
}

const lines = ref([
  { date: '2026-10-28', type: 'Tea & Refreshments', merchant: 'Chai Point', hasGst: false, billNo: 'UPI/998127391', amount: 350, receiptName: '', spentBy: 'Front Desk' },
  { date: '2026-10-27', type: 'Office Supplies & Stationery', merchant: 'Staples Express', hasGst: true, billNo: 'INV-STP-0012', amount: 1250, receiptName: '', spentBy: 'Front Desk' },
]);

function addLine() {
  lines.value.push({
    date: formData.value.postingDate,
    type: 'Tea & Refreshments',
    merchant: '',
    hasGst: false,
    billNo: '',
    amount: 0,
    receiptName: '',
    spentBy: 'Front Desk',
  });
}

function duplicateLastLine() {
  if (!lines.value.length) return;
  const last = lines.value[lines.value.length - 1];
  lines.value.push({ ...last, billNo: '', receiptName: '' });
}

function removeLine(idx) {
  lines.value.splice(idx, 1);
}

function triggerFileInput(idx) {
  const el = document.getElementById(`file-input-${idx}`);
  if (el) el.click();
}

function handleFileUpload(event, idx) {
  const file = event.target.files?.[0];
  if (file) {
    lines.value[idx].receiptName = file.name;
    emitToast(`Attached photo "${file.name}" to line #${idx + 1}.`);
  }
}

const totalVoucherAmount = computed(() => {
  return lines.value.reduce((acc, l) => acc + (Number(l.amount) || 0), 0);
});

function handleSave() {
  isSaved.value = true;
  emitToast('Petty Cash Voucher saved successfully.');
}

function handleSubmitL1() {
  currentStep.value = 2;
  formData.value.status = 'Pending Admin Approval';
  emitToast('Voucher submitted for Admin L1 approval.');
}
</script>

