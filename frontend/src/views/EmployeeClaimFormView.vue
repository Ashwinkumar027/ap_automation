<template>
  <div>
    <!-- Top Breadcrumb & Actions -->
    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;">
      <div style="display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--muted);">
        <router-link to="/employee-claims" style="color: var(--purple); text-decoration: none; font-weight: 700;">← Back to Claims</router-link>
        <span>/</span>
        <span>Employee Reimbursement Claim</span>
        <span>/</span>
        <strong style="color: var(--ink);">{{ claimId || 'New Claim' }}</strong>
        <span v-if="!isSaved" style="background: #fff3d7; color: #bf7b00; font-size: 10px; font-weight: 800; padding: 2px 7px; border-radius: 6px;">Not Saved</span>
      </div>

      <div style="display: flex; gap: 10px; align-items: center;">
        <div style="text-align: right; margin-right: 8px;">
          <small style="color: var(--muted); font-size: 10px; text-transform: uppercase; font-weight: 700;">Net Payable</small>
          <div style="font-size: 20px; font-weight: 800; color: var(--purple-dark);">
            ₹ {{ finalPayableAmount.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }}
          </div>
        </div>
        <router-link to="/employee-claims" class="secondary-btn" style="text-decoration: none; padding: 8px 14px; font-size: 11px;">Cancel</router-link>
        <button class="primary-btn" style="padding: 8px 18px; font-size: 11px;" @click="handleSave">Save Claim</button>
      </div>
    </div>

    <!-- 9-Step Approval Workflow Stepper (Matching Screenshot 15) -->
    <div style="background: rgba(255,255,255,0.92); border: 1px solid #e7e8f8; border-radius: 18px; padding: 14px 18px; margin-bottom: 20px; box-shadow: var(--shadow); overflow-x: auto;">
      <div style="display: flex; align-items: center; justify-content: space-between; min-width: 840px; gap: 6px;">
        <div v-for="(step, idx) in steps" :key="step.name" style="display: flex; flex-direction: column; align-items: center; flex: 1; text-align: center;">
          <div
            :style="{
              width: '28px',
              height: '28px',
              borderRadius: '50%',
              display: 'grid',
              placeItems: 'center',
              fontSize: '11px',
              fontWeight: '800',
              background: currentStep >= idx + 1 ? 'linear-gradient(135deg, #704cff, #542ff0)' : '#f0f1fa',
              color: currentStep >= idx + 1 ? 'white' : '#7b83a3',
              boxShadow: currentStep === idx + 1 ? '0 0 0 3px #dfd7ff' : 'none'
            }"
          >
            {{ idx + 1 }}
          </div>
          <span style="font-size: 10px; font-weight: 800; margin-top: 6px; color: var(--ink);">{{ step.name }}</span>
          <small style="font-size: 9px; color: var(--muted); margin-top: 2px;">{{ step.role }}</small>
        </div>
      </div>
    </div>

    <!-- Category Selection Tiles (Matching Screenshot 15) -->
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 24px;">
      <div
        v-for="cat in categories"
        :key="cat.id"
        @click="selectedCategory = cat.id"
        :style="{
          padding: '14px 16px',
          borderRadius: '16px',
          background: selectedCategory === cat.id ? 'linear-gradient(145deg, #faf9ff, #f3efff)' : 'white',
          border: selectedCategory === cat.id ? '2px solid #6542f5' : '1px solid #e7e8f8',
          boxShadow: selectedCategory === cat.id ? '0 8px 20px rgba(101,66,245,0.12)' : 'var(--shadow)',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          transition: '0.18s'
        }"
      >
        <div style="font-size: 24px;">{{ cat.icon }}</div>
        <div>
          <strong style="display: block; font-size: 12px; color: var(--ink);">{{ cat.title }}</strong>
          <small style="font-size: 10px; color: var(--muted);">{{ cat.subtitle }}</small>
        </div>
      </div>
    </div>

    <!-- Main Form Container -->
    <div style="background: rgba(255,255,255,0.92); border: 1px solid #e7e8f8; border-radius: 20px; padding: 24px; box-shadow: var(--shadow);">
      <!-- Employee & Claim Information -->
      <h3 style="margin: 0 0 16px; font-size: 13px; font-weight: 800; color: #434c6d; text-transform: uppercase; letter-spacing: 0.5px;">
        Employee & Claim Information
      </h3>

      <div class="form-grid" style="margin-bottom: 20px;">
        <div class="field">
          <label>Employee ID *</label>
          <div style="position: relative;">
            <input
              v-model="formData.employeeId"
              list="employee-list"
              placeholder="Type or Select Employee ID (e.g. EMP9002)"
              @input="onSearchEmployee"
              @change="onSearchEmployee"
              style="font-weight: 700; color: var(--purple-dark);"
            />
            <datalist id="employee-list">
              <option v-for="emp in employeesList" :key="emp.name" :value="emp.name">
                {{ emp.employee_name }} - {{ emp.company }}
              </option>
            </datalist>
          </div>
        </div>
        <div class="field">
          <label>Claim Date *</label>
          <input v-model="formData.claimDate" type="date" />
        </div>
        <div class="field">
          <label>Employee Name</label>
          <input :value="formData.employeeName" disabled style="background: #f7f8fc; font-weight: 700; color: var(--ink);" />
        </div>
        <div class="field">
          <label>Status</label>
          <input :value="formData.status" disabled style="background: #f7f8fc; font-weight: 700; color: #d98a00;" />
        </div>
        <div class="field">
          <label>HRMS Legal Entity *</label>
          <input :value="formData.legalEntity" disabled style="background: #f7f8fc; font-weight: 700;" />
        </div>
        <div class="field">
          <label>Claim Category *</label>
          <select v-model="selectedCategory" style="font-weight: 700;">
            <option value="client_visit">Client Visit Travel</option>
            <option value="general">General Expense</option>
            <option value="team_bonding">Team Bonding</option>
            <option value="dinner">Dinner Allowance</option>
            <option value="branch">Branch Expense</option>
          </select>
        </div>
      </div>

      <!-- Salary Bank Details (HRMS Verified) Card (Matching Screenshot 15 & 16) -->
      <div class="bank-details-card">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
          <div style="display: flex; align-items: center; gap: 8px;">
            <span style="font-size: 18px;">🏛️</span>
            <strong style="font-size: 13px; color: var(--purple-dark); font-weight: 800;">
              Salary Bank Details (HRMS Verified)
            </strong>
            <span style="background: #e6f9f0; color: #058f58; border: 1px solid #b7f0d4; font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 999px;">
              ✓ Verified Salary Account
            </span>
          </div>
          <small style="color: var(--muted); font-size: 10px; font-weight: 600;">
            Zero-Advance Policy ACM-POL-01: Direct Disbursal to Employee Account
          </small>
        </div>

        <div style="display: grid; grid-template-columns: 1.5fr 2.5fr 1.5fr; gap: 16px; background: #ffffff; padding: 14px 18px; border: 1px solid #e8e6fa; border-radius: 12px;">
          <div>
            <small style="color: var(--muted); font-size: 10px; display: block; margin-bottom: 4px; font-weight: 700;">BANK NAME</small>
            <strong style="font-size: 13px; color: var(--ink);">{{ bankInfo.bankName || 'HDFC Bank Limited' }}</strong>
          </div>
          <div>
            <small style="color: var(--muted); font-size: 10px; display: block; margin-bottom: 4px; font-weight: 700;">ACCOUNT NUMBER</small>
            <div style="display: flex; align-items: center; gap: 8px;">
              <strong style="font-size: 13px; color: var(--ink); letter-spacing: 0.5px;">
                {{ showFullAccount ? bankInfo.acNo : maskAccount(bankInfo.acNo || '50100456789012') }}
              </strong>
              <button type="button" @click="showFullAccount = !showFullAccount" style="border: 0; background: transparent; cursor: pointer; font-size: 10px; font-weight: 700; color: var(--purple);">
                {{ showFullAccount ? 'Hide' : 'Show' }}
              </button>
            </div>
          </div>
          <div>
            <small style="color: var(--muted); font-size: 10px; display: block; margin-bottom: 4px; font-weight: 700;">IFSC CODE</small>
            <strong style="font-size: 13px; color: var(--ink);">{{ bankInfo.ifsc || 'HDFC0001234' }}</strong>
          </div>
        </div>
      </div>

      <!-- Section: Client Visit Travel (Screenshot 16) -->
      <div v-if="selectedCategory === 'client_visit'" style="margin-top: 22px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
          <div>
            <h4 style="margin: 0; font-size: 12px; font-weight: 800; color: #434c6d; text-transform: uppercase;">
              Client Visits & Multi-Stop Travel (Policy ACM-TRP-1.0)
            </h4>
            <p style="margin: 3px 0 0; font-size: 11px; color: var(--muted);">
              Record each visit leg, select mode of travel, enter KM, and attach parking/toll proofs.
            </p>
          </div>
          <button type="button" class="primary-btn" style="padding: 7px 13px; font-size: 11px;" @click="addLeg">
            ＋ Add Visit Leg
          </button>
        </div>

        <div style="overflow-x: auto; margin-bottom: 16px; border: 1px solid #e7e9fa; border-radius: 14px; background: #ffffff;">
          <table class="grid-table">
            <thead>
              <tr>
                <th style="width: 38px; text-align: center;">#</th>
                <th style="width: 120px;">VISIT DATE *</th>
                <th style="min-width: 140px;">CLIENT NAME</th>
                <th style="min-width: 120px;">FROM</th>
                <th style="min-width: 120px;">TO</th>
                <th style="width: 170px;">MODE OF TRAVEL</th>
                <th style="width: 70px;">KM</th>
                <th style="width: 100px;">MILEAGE (₹)</th>
                <th style="width: 100px;">TOLL/PARKING</th>
                <th style="width: 100px;">SUBTOTAL (₹)</th>
                <th style="width: 120px;">RECEIPT</th>
                <th style="width: 45px; text-align: center;">ACTION</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(leg, idx) in itinerary" :key="idx">
                <td style="text-align: center; font-weight: 800; color: var(--muted);">{{ idx + 1 }}</td>
                <td>
                  <input type="date" v-model="leg.date" class="grid-input" />
                </td>
                <td>
                  <input v-model="leg.client" placeholder="Client Office" class="grid-input" />
                </td>
                <td>
                  <input v-model="leg.from" placeholder="Start Point" class="grid-input" />
                </td>
                <td>
                  <input v-model="leg.to" placeholder="Destination" class="grid-input" />
                </td>
                <td>
                  <select v-model="leg.mode" class="grid-select" @change="recalcMileage(leg)">
                    <option>Personal Car (₹10/km)</option>
                    <option>Two Wheeler (₹5/km)</option>
                    <option>Cab / Taxi (Actuals)</option>
                    <option>Public Transport</option>
                  </select>
                </td>
                <td>
                  <input
                    v-model.number="leg.km"
                    type="number"
                    step="0.1"
                    placeholder="0"
                    class="grid-input"
                    style="text-align: right;"
                    @input="recalcMileage(leg)"
                  />
                </td>
                <td style="text-align: right; font-weight: 700;">
                  ₹ {{ (leg.mileage || 0).toLocaleString('en-IN') }}
                </td>
                <td>
                  <input
                    v-model.number="leg.toll"
                    type="number"
                    placeholder="0"
                    class="grid-input"
                    style="text-align: right;"
                  />
                </td>
                <td style="text-align: right; font-weight: 800; color: var(--purple-dark);">
                  ₹ {{ ((leg.mileage || 0) + (leg.toll || 0)).toLocaleString('en-IN') }}
                </td>
                <td>
                  <input type="file" :id="`leg-file-${idx}`" style="display: none;" @change="handleLegUpload($event, idx)" />
                  <div v-if="leg.receiptName" class="receipt-attached-pill">
                    <span>📎 {{ leg.receiptName }}</span>
                    <button type="button" @click="leg.receiptName = ''" style="border:0;background:transparent;cursor:pointer;color:#e43f50;font-weight:bold;margin-left:4px;">✕</button>
                  </div>
                  <button v-else type="button" class="receipt-upload-btn" @click="triggerLegFile(idx)">📷 Attach</button>
                </td>
                <td style="text-align: center;">
                  <button type="button" class="delete-row-btn" @click="removeLeg(idx)" title="Delete">✕</button>
                </td>
              </tr>
              <tr v-if="!itinerary.length">
                <td colspan="12" style="text-align: center; padding: 22px; color: var(--muted);">
                  No travel legs added yet. Click <strong>[+ Add Visit Leg]</strong> to begin.
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Travel Mileage & Food Per Diem Summary (Screenshot 16) -->
        <div style="background: #faf9ff; border: 1px solid #e7e0ff; border-radius: 16px; padding: 18px; margin-bottom: 16px;">
          <h4 style="margin: 0 0 12px; font-size: 12px; font-weight: 800; color: var(--purple-dark);">
            Travel Mileage & Food Per Diem Summary
          </h4>

          <div style="display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 12px; margin-bottom: 14px;">
            <div class="detail">
              <small>TOTAL DISTANCE</small>
              <strong>{{ totalDistance }} KM</strong>
            </div>
            <div class="detail">
              <small>TOTAL MILEAGE (₹)</small>
              <strong>₹ {{ totalMileage.toLocaleString('en-IN') }}</strong>
            </div>
            <div class="detail">
              <small>TOTAL TOLL & PARKING</small>
              <strong>₹ {{ totalToll.toLocaleString('en-IN') }}</strong>
            </div>
            <div class="detail" style="background: #eeeafe;">
              <small>TOTAL TRAVEL CLAIMED</small>
              <strong style="color: var(--purple-dark);">₹ {{ totalTravelAllowance.toLocaleString('en-IN') }}</strong>
            </div>
          </div>

          <!-- Per Diem Tag -->
          <div style="padding-top: 12px; border-top: 1px solid #e8bfff; display: flex; align-items: center; gap: 20px; flex-wrap: wrap;">
            <label style="display: flex; align-items: center; gap: 6px; font-size: 11px; font-weight: 700; cursor: pointer;">
              <input type="checkbox" v-model="perDiem.enabled" class="grid-check" /> Claim Food Per Diem
            </label>
            <div v-if="perDiem.enabled" style="display: flex; align-items: center; gap: 14px; font-size: 11px;">
              <label>How many days?
                <input v-model.number="perDiem.days" type="number" min="1" max="30" class="grid-input" style="width: 55px; display: inline-block; margin-left: 6px;" />
              </label>
              <label style="display: flex; align-items: center; gap: 5px;"><input type="checkbox" v-model="perDiem.breakfast" class="grid-check" /> Breakfast (₹100)</label>
              <label style="display: flex; align-items: center; gap: 5px;"><input type="checkbox" v-model="perDiem.lunch" class="grid-check" /> Lunch (₹200)</label>
              <label style="display: flex; align-items: center; gap: 5px;"><input type="checkbox" v-model="perDiem.dinner" class="grid-check" /> Dinner (₹200)</label>
              <span style="font-weight: 800; color: #08a96a;">Per Diem Allowance: ₹ {{ totalPerDiem.toLocaleString('en-IN') }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Section: General / Branch / Dinner / Team Expense Grid -->
      <div v-else style="margin-top: 22px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
          <div>
            <h4 style="margin: 0; font-size: 12px; font-weight: 800; color: #434c6d; text-transform: uppercase;">
              Expense Lines (Mandatory Bill Proofs) — {{ categoryTitle }}
            </h4>
            <p style="margin: 3px 0 0; font-size: 11px; color: var(--muted);">
              Enter itemized expenses meeting Indian statutory tax invoicing guidelines.
            </p>
          </div>
          <button type="button" class="primary-btn" style="padding: 7px 13px; font-size: 11px;" @click="addGeneralLine">
            ＋ Add Expense Line
          </button>
        </div>

        <div style="overflow-x: auto; margin-bottom: 16px; border: 1px solid #e7e9fa; border-radius: 14px; background: #ffffff;">
          <table class="grid-table">
            <thead>
              <tr>
                <th style="width: 38px; text-align: center;">#</th>
                <th style="width: 130px;">EXPENSE DATE *</th>
                <th style="width: 180px;">EXPENSE SUBTYPE *</th>
                <th style="min-width: 150px;">MERCHANT / RESTAURANT</th>
                <th style="width: 150px;">BILL # / TAX INVOICE</th>
                <th style="width: 70px; text-align: center;">B2B?</th>
                <th style="width: 130px;">AMOUNT (₹) *</th>
                <th style="width: 130px;">RECEIPT</th>
                <th style="width: 45px; text-align: center;">ACTION</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(line, idx) in generalLines" :key="idx">
                <td style="text-align: center; font-weight: 800; color: var(--muted);">{{ idx + 1 }}</td>
                <td>
                  <input type="date" v-model="line.date" class="grid-input" />
                </td>
                <td>
                  <select v-model="line.subtype" class="grid-select">
                    <option>Team Lunch / Dinner</option>
                    <option>Courier / Mail</option>
                    <option>Office Stationery</option>
                    <option>Software Subscription</option>
                    <option>Hardware & Cable</option>
                    <option>Cab / Local Travel</option>
                    <option>Other</option>
                  </select>
                </td>
                <td>
                  <input v-model="line.merchant" placeholder="Merchant Name" class="grid-input" />
                </td>
                <td>
                  <input v-model="line.invoice" placeholder="INV-0001" class="grid-input" />
                </td>
                <td style="text-align: center;">
                  <input type="checkbox" v-model="line.isB2b" class="grid-check" />
                </td>
                <td>
                  <input
                    v-model.number="line.amount"
                    type="number"
                    step="0.01"
                    placeholder="0.00"
                    class="grid-input"
                    style="font-weight: 800; text-align: right; color: var(--ink);"
                  />
                </td>
                <td>
                  <input type="file" :id="`gen-file-${idx}`" style="display: none;" @change="handleGenUpload($event, idx)" />
                  <div v-if="line.receiptName" class="receipt-attached-pill">
                    <span>📎 {{ line.receiptName }}</span>
                    <button type="button" @click="line.receiptName = ''" style="border:0;background:transparent;cursor:pointer;color:#e43f50;font-weight:bold;margin-left:4px;">✕</button>
                  </div>
                  <button v-else type="button" class="receipt-upload-btn" @click="triggerGenFile(idx)">📷 Attach</button>
                </td>
                <td style="text-align: center;">
                  <button type="button" class="delete-row-btn" @click="removeGeneralLine(idx)" title="Delete">✕</button>
                </td>
              </tr>
              <tr v-if="!generalLines.length">
                <td colspan="9" style="text-align: center; padding: 22px; color: var(--muted);">
                  No expense lines added yet. Click <strong>[+ Add Expense Line]</strong> to begin.
                </td>
              </tr>
            </tbody>
            <tfoot v-if="generalLines.length" style="background: #fafaff; border-top: 2px solid #e7e9fa; font-weight: 800;">
              <tr>
                <td colspan="6" style="text-align: right; padding: 10px 14px; color: var(--muted); text-transform: uppercase; font-size: 10px;">
                  Grand Total
                </td>
                <td style="text-align: right; padding: 10px 8px; font-size: 13px; color: var(--purple-dark);">
                  ₹ {{ generalLinesTotal.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }}
                </td>
                <td colspan="2"></td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>

      <!-- Claim Settlement Summary -->
      <div style="border-top: 1px solid #edf0fa; padding-top: 20px; margin-top: 24px; display: flex; justify-content: space-between; align-items: flex-end;">
        <div>
          <h4 style="margin: 0 0 6px; font-size: 12px; font-weight: 800;">Claim Settlement Summary</h4>
          <p style="margin: 0; font-size: 11px; color: var(--muted);">
            Direct reimbursement policy — <strong style="color: #08a96a;">strictly zero advance deductions</strong>. 100% payable to employee verified salary account.
          </p>
        </div>

        <div style="text-align: right;">
          <div style="font-size: 11px; color: var(--muted); margin-bottom: 4px;">Net Payable to Employee</div>
          <div style="font-size: 26px; font-weight: 800; color: var(--purple-dark); letter-spacing: -0.5px;">
            ₹ {{ finalPayableAmount.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }}
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

const claimId = computed(() => route.params.id || '');
const isSaved = ref(false);
const currentStep = ref(1);
const showFullAccount = ref(false);
const employeesList = ref([]);

const steps = [
  { name: 'Draft / Prep', role: 'Employee' },
  { name: 'Manager Review', role: 'L1 Lead' },
  { name: 'Reception Approval', role: 'Admin' },
  { name: 'Admin L1 Sign-Off', role: 'L1 Approver' },
  { name: 'Admin L2 Auth', role: 'L2 Approver' },
  { name: 'Accounts Audit', role: 'L1 Audit' },
  { name: 'Final Sanction', role: 'Accounts Director' },
  { name: 'Payment Scheduled', role: 'Friday Batch' },
  { name: 'Settled / Paid', role: 'Bank UTR' },
];

const categories = [
  { id: 'client_visit', title: 'Client Visit Travel', subtitle: 'Multi-Client Route & Mileage', icon: '🚗' },
  { id: 'general', title: 'General Expense', subtitle: 'Itemized Bill Proofs', icon: '📦' },
  { id: 'team_bonding', title: 'Team Bonding', subtitle: 'Individual Wallet Ledger', icon: '🍕' },
  { id: 'dinner', title: 'Dinner Allowance', subtitle: 'Late Shift Cutoff', icon: '🌙' },
  { id: 'branch', title: 'Branch Expense', subtitle: 'Repairs & Operations', icon: '🏢' },
];

const selectedCategory = ref('client_visit');
const categoryTitle = computed(() => categories.find(c => c.id === selectedCategory.value)?.title || 'Client Visit Travel');

const formData = ref({
  employeeId: 'EMP9002',
  employeeName: 'Anita Verma (Consultant)',
  claimDate: new Date().toISOString().split('T')[0],
  status: 'Draft',
  legalEntity: 'Anshul A Gupta & Associates',
  department: 'Consulting',
});

const bankInfo = ref({
  bankName: 'HDFC Bank Limited',
  acNo: '50100456789012',
  ifsc: 'HDFC0001234',
});

function maskAccount(ac) {
  if (!ac) return '•••• •••• 4455';
  return '•••• •••• ' + String(ac).slice(-4);
}

function onSearchEmployee() {
  const query = formData.value.employeeId.trim().toUpperCase();
  if (!query) return;

  const found = employeesList.value.find(e =>
    e.name.toUpperCase() === query ||
    (e.employee_name && e.employee_name.toUpperCase().includes(query))
  );

  if (found) {
    formData.value.employeeId = found.name;
    formData.value.employeeName = found.employee_name || 'Employee';
    formData.value.legalEntity = found.company || 'Anshul A Gupta & Associates';
    formData.value.department = found.department || 'Operations';
    bankInfo.value.bankName = found.bank_name || 'HDFC Bank Limited';
    bankInfo.value.acNo = found.bank_ac_no || '50100456789012';
    bankInfo.value.ifsc = found.ifsc_code || 'HDFC0001234';
    emit('toast', `Loaded HRMS verified details for ${found.employee_name} (${found.name})`);
  }
}

onMounted(async () => {
  try {
    const list = await frappeGetDocList('Employee', {
      fields: ['name', 'employee_name', 'department', 'company', 'bank_name', 'bank_ac_no', 'ifsc_code'],
      limit: 100,
    });
    if (list && list.length) {
      employeesList.value = list;
      onSearchEmployee();
    }
  } catch (err) {
    console.warn('Could not fetch employees list:', err);
  }
});

// Client Visit Itinerary
const itinerary = ref([
  { date: '2026-10-24', client: 'Grand Convention Resort', from: 'Chennai HQ', to: 'Mahabalipuram', mode: 'Personal Car (₹10/km)', km: 45, mileage: 450, toll: 120, receiptName: '' },
  { date: '2026-10-24', client: 'Event Craft Media', from: 'Mahabalipuram', to: 'Chennai HQ', mode: 'Personal Car (₹10/km)', km: 45, mileage: 450, toll: 120, receiptName: '' },
]);

function recalcMileage(leg) {
  const rate = leg.mode.includes('Car') ? 10 : leg.mode.includes('Two') ? 5 : 0;
  leg.mileage = (leg.km || 0) * rate;
}

function addLeg() {
  itinerary.value.push({
    date: formData.value.claimDate,
    client: '',
    from: 'Chennai HQ',
    to: '',
    mode: 'Personal Car (₹10/km)',
    km: 0,
    mileage: 0,
    toll: 0,
    receiptName: '',
  });
}

function removeLeg(idx) {
  itinerary.value.splice(idx, 1);
}

function triggerLegFile(idx) {
  const el = document.getElementById(`leg-file-${idx}`);
  if (el) el.click();
}

function handleLegUpload(event, idx) {
  const file = event.target.files?.[0];
  if (file) {
    itinerary.value[idx].receiptName = file.name;
    emit('toast', `Attached proof "${file.name}" to trip leg #${idx + 1}.`);
  }
}

// Per Diem details
const perDiem = ref({
  enabled: true,
  days: 1,
  breakfast: true,
  lunch: true,
  dinner: true,
});

const totalDistance = computed(() => itinerary.value.reduce((acc, leg) => acc + (leg.km || 0), 0));
const totalMileage = computed(() => itinerary.value.reduce((acc, leg) => acc + (leg.mileage || 0), 0));
const totalToll = computed(() => itinerary.value.reduce((acc, leg) => acc + (leg.toll || 0), 0));

const totalPerDiem = computed(() => {
  if (!perDiem.value.enabled) return 0;
  let daily = 0;
  if (perDiem.value.breakfast) daily += 100;
  if (perDiem.value.lunch) daily += 200;
  if (perDiem.value.dinner) daily += 200;
  return daily * (perDiem.value.days || 1);
});

const totalTravelAllowance = computed(() => totalMileage.value + totalToll.value + totalPerDiem.value);

// General lines
const generalLines = ref([
  { date: '2026-10-25', subtype: 'Team Lunch / Dinner', merchant: 'Paradise Biryani', invoice: 'INV-PB-991', isB2b: false, amount: 3450, receiptName: '' },
]);

function addGeneralLine() {
  generalLines.value.push({
    date: formData.value.claimDate,
    subtype: 'Team Lunch / Dinner',
    merchant: '',
    invoice: '',
    isB2b: false,
    amount: 0,
    receiptName: '',
  });
}

function removeGeneralLine(idx) {
  generalLines.value.splice(idx, 1);
}

function triggerGenFile(idx) {
  const el = document.getElementById(`gen-file-${idx}`);
  if (el) el.click();
}

function handleGenUpload(event, idx) {
  const file = event.target.files?.[0];
  if (file) {
    generalLines.value[idx].receiptName = file.name;
    emit('toast', `Attached receipt "${file.name}" to line #${idx + 1}.`);
  }
}

const generalLinesTotal = computed(() => {
  return generalLines.value.reduce((acc, l) => acc + (Number(l.amount) || 0), 0);
});

const finalPayableAmount = computed(() => {
  if (selectedCategory.value === 'client_visit') {
    return totalTravelAllowance.value;
  }
  return generalLinesTotal.value;
});

function handleSave() {
  isSaved.value = true;
  emit('toast', 'Employee reimbursement claim saved successfully.');
}
</script>
