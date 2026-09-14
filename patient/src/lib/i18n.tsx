/**
 * English and Nepali, and Bikram Sambat dates.
 *
 * **The patient app was English-only**, for an audience that most needs it in
 * Nepali: the patient in Bhaktapur checking a result on a phone, or the son
 * managing his mother's appointments. And every date was Gregorian, which is
 * not the calendar a Nepali patient plans a hospital visit in — "the 13th" of
 * the wrong calendar is a missed appointment.
 *
 * Two decisions:
 *
 * - **Bikram Sambat comes from a maintained library** (`nepali-date-converter`),
 *   not a table typed here. BS month lengths are not computable; they are
 *   published year by year, and a hand-copied table in a medical app is a way
 *   to tell a patient the wrong day. The library was checked against the
 *   known new-year dates (1 Baishakh 2081, 2082 and 2083) before it was used.
 * - **Numbers stay in the digits the hospital prints.** A hospital number, a
 *   bill total, a phone number are read aloud at a counter and typed into
 *   eSewa; they stay 0–9 in both languages. Dates in Nepali are written the
 *   way Nepali dates are written — "२७ भाद्र २०८३".
 *
 * Content the hospital writes — a doctor's name, a diagnosis, a report — is
 * shown as written. What this app itself says is translated.
 */

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import NepaliDate from "nepali-date-converter";

export type Lang = "en" | "ne";

const STORAGE_KEY = "nirova.portal.lang";

function initial(): Lang {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "en" || saved === "ne") return saved;
  } catch {
    /* private browsing */
  }
  return typeof navigator !== "undefined" && navigator.language?.startsWith("ne") ? "ne" : "en";
}

/**
 * The active language, readable outside React — the date helpers are plain
 * functions used all over the app. Kept in step with the provider's state,
 * whose change re-renders everything that formats.
 */
let active: Lang = initial();

// ---------------------------------------------------------------------------
// Strings
// ---------------------------------------------------------------------------

const STRINGS = {
  "app.title": { en: "My health record", ne: "मेरो स्वास्थ्य रेकर्ड" },
  "app.subtitle": { en: "Your appointments, results and bills.", ne: "तपाईंका भेटघाट, नतिजा र बिल।" },
  "signin.title": { en: "Sign in", ne: "साइन इन" },
  "signin.hint": { en: "With the phone number you gave at the hospital.", ne: "अस्पतालमा दिनुभएको फोन नम्बरबाट।" },
  "signin.hospital": { en: "Hospital", ne: "अस्पताल" },
  "signin.phone": { en: "Phone number", ne: "फोन नम्बर" },
  "signin.password": { en: "Password", ne: "पासवर्ड" },
  "signin.submit": { en: "Sign in", ne: "साइन इन गर्नुहोस्" },
  "signin.code": { en: "I have a code from the hospital", ne: "मसँग अस्पतालबाट पाएको कोड छ" },
  "signin.lockout": {
    en: "After five wrong attempts you will be locked out for a few minutes.",
    ne: "पाँच पटक गलत भएमा केही मिनेटका लागि साइन इन रोकिनेछ।",
  },
  "emergency.title": { en: "In an emergency", ne: "आपतकालमा" },
  "emergency.body": {
    en: "Do not use this app. Go to the emergency department, or call an ambulance on 102.",
    ne: "यो एप प्रयोग नगर्नुहोस्। आपतकालीन विभागमा जानुहोस्, वा १०२ मा एम्बुलेन्स बोलाउनुहोस्।",
  },
  "emergency.call": { en: "Call {name}", ne: "{name}मा फोन गर्नुहोस्" },
  "emergency.hospital": { en: "the hospital", ne: "अस्पताल" },

  "home.greeting.morning": { en: "Good morning", ne: "शुभ प्रभात" },
  "home.greeting.afternoon": { en: "Good afternoon", ne: "नमस्ते" },
  "home.greeting.evening": { en: "Good evening", ne: "शुभ सन्ध्या" },
  "home.mrn": { en: "Hospital number", ne: "अस्पताल नम्बर" },
  "home.blood": { en: "Blood group", ne: "रक्त समूह" },
  "home.bloodUnknown": { en: "Not recorded", ne: "रेकर्ड छैन" },
  "home.age": { en: "Age", ne: "उमेर" },
  "home.showAtDesk": { en: "Show this at the registration desk.", ne: "दर्ता काउन्टरमा यो देखाउनुहोस्।" },
  "home.upNext": { en: "Up next", ne: "अर्को भेट" },
  "home.noAppointment": { en: "No appointment booked.", ne: "कुनै भेट बुक गरिएको छैन।" },
  "home.bookVisit": { en: "Book a visit", ne: "भेट बुक गर्नुहोस्" },
  "home.forYou": { en: "For you", ne: "तपाईंका लागि" },
  "home.nothingWaiting": {
    en: "Nothing waiting. New results, bills and messages will appear here.",
    ne: "अहिले केही बाँकी छैन। नयाँ नतिजा, बिल र सन्देश यहाँ देखिनेछन्।",
  },
  "home.discussedOne": { en: "A doctor will call you about a result", ne: "एउटा नतिजाबारे डाक्टरले तपाईंलाई फोन गर्नुहुनेछ" },
  "home.discussedMany": { en: "A doctor will call you about {n} results", ne: "{n} वटा नतिजाबारे डाक्टरले तपाईंलाई फोन गर्नुहुनेछ" },
  "home.discussedDetail": { en: "Some results are better explained than read alone.", ne: "केही नतिजा एक्लै पढ्नुभन्दा बुझाइदिनु राम्रो हुन्छ।" },
  "home.resultsOne": { en: "1 result to read", ne: "१ वटा नतिजा हेर्न बाँकी" },
  "home.resultsMany": { en: "{n} results to read", ne: "{n} वटा नतिजा हेर्न बाँकी" },
  "home.latest": { en: "Latest: {test}", ne: "पछिल्लो: {test}" },
  "home.outsideRange": { en: " — some values are outside the usual range", ne: " — केही मान सामान्य दायराभन्दा बाहिर छन्" },
  "home.toPay": { en: "{amount} to pay", ne: "तिर्न बाँकी {amount}" },
  "home.payHow": {
    en: "Pay at the cashier, or by eSewa or Khalti with the bill number.",
    ne: "क्यासियरमा, वा बिल नम्बरसहित ई-सेवा वा खल्तीबाट तिर्न सकिन्छ।",
  },
  "home.messagesOne": { en: "1 new message", ne: "१ नयाँ सन्देश" },
  "home.messagesMany": { en: "{n} new messages", ne: "{n} नयाँ सन्देश" },
  "home.fromHospital": { en: "From the hospital.", ne: "अस्पतालबाट।" },
  "home.medicines": { en: "Your medicines", ne: "तपाईंका औषधि" },
  "home.all": { en: "All", ne: "सबै" },
  "home.until": { en: "until {date}", ne: "{date} सम्म" },
  "home.signOut": { en: "Sign out", ne: "साइन आउट" },
  "home.signedIn": { en: "Where I am signed in", ne: "म कहाँ कहाँ साइन इन छु" },
  "home.proxyTitle": { en: "You are viewing {name}'s record", ne: "तपाईं {name} को रेकर्ड हेर्दै हुनुहुन्छ" },
  "home.proxyBody": {
    en: "As their {relationship}. They or the hospital can end this at any time.",
    ne: "उहाँको {relationship} को रूपमा। उहाँ वा अस्पतालले जुनसुकै बेला यो बन्द गर्न सक्नुहुन्छ।",
  },

  "nav.home": { en: "Home", ne: "गृह" },
  "nav.results": { en: "Results", ne: "नतिजा" },
  "nav.visits": { en: "Visits", ne: "भेटघाट" },
  "nav.messages": { en: "Messages", ne: "सन्देश" },
  "nav.me": { en: "Me", ne: "म" },

  "section.results": { en: "Test results", ne: "जाँचका नतिजा" },
  "section.appointments": { en: "Appointments", ne: "भेटघाट" },
  "section.invoices": { en: "Bills", ne: "बिल" },
  "section.prescriptions": { en: "Medicines", ne: "औषधि" },
  "section.referrals": { en: "Referrals", ne: "रेफरल" },
  "section.access": { en: "Who saw my record", ne: "मेरो रेकर्ड कसले हेर्‍यो" },
  "section.messages": { en: "Messages", ne: "सन्देश" },
  "section.sessions": { en: "Where I am signed in", ne: "म कहाँ कहाँ साइन इन छु" },
  "section.profile": { en: "My details", ne: "मेरो विवरण" },
  "section.home": { en: "Home", ne: "गृह" },

  "bills.outstanding": { en: "Outstanding", ne: "तिर्न बाँकी" },
  "bills.toPay": { en: "{amount} to pay", ne: "तिर्न बाँकी {amount}" },
  "bills.receipt": { en: "Receipt", ne: "रसिद" },
  "bills.none": { en: "No bills.", ne: "कुनै बिल छैन।" },
  "bills.refund": { en: "refund", ne: "फिर्ता" },
  "bills.payNow": { en: "Pay now", ne: "अहिले तिर्नुहोस्" },
  "bills.payWith": { en: "Pay with {wallet}", ne: "{wallet} बाट तिर्नुहोस्" },
  "bills.testMode": { en: "Test mode — no money is taken", ne: "परीक्षण मोड — पैसा काटिँदैन" },
  "bills.opening": { en: "Opening {wallet}…", ne: "{wallet} खुल्दैछ…" },
  "bills.checking": { en: "Checking your payment…", ne: "तपाईंको भुक्तानी जाँच्दै…" },
  "bills.paid": { en: "Paid. Receipt {receipt}.", ne: "भुक्तानी भयो। रसिद {receipt}।" },
  "bills.pending": { en: "Your wallet has not confirmed this yet. We will keep checking.", ne: "तपाईंको वालेटले अझै पुष्टि गरेको छैन। हामी जाँचिरहनेछौं।" },
  "bills.notPaid": { en: "This payment did not go through. Nothing was taken.", ne: "यो भुक्तानी भएन। कुनै रकम काटिएको छैन।" },
  "bills.attention": { en: "The hospital has been told and will sort this out.", ne: "अस्पताललाई जानकारी गराइएको छ, उहाँहरूले मिलाउनुहुनेछ।" },
  "bills.done": { en: "Done", ne: "भयो" },

  "signup.created": { en: "Account created", ne: "खाता बन्यो" },
  "signup.setUp": { en: "Set up your account", ne: "आफ्नो खाता बनाउनुहोस्" },
  "signup.hospital": { en: "Hospital", ne: "अस्पताल" },
  "signup.mrn": { en: "Number on your card", ne: "तपाईंको कार्डमा भएको नम्बर" },
  "signup.code": { en: "Code from the desk", ne: "डेस्कबाट पाएको कोड" },
  "signup.phone": { en: "Your phone number", ne: "तपाईंको फोन नम्बर" },
  "signup.password": { en: "Choose a password", ne: "पासवर्ड छान्नुहोस्" },
  "empty.results": { en: "No results yet.", ne: "अहिलेसम्म कुनै नतिजा छैन।" },
  "empty.medicines": { en: "No medicines prescribed.", ne: "कुनै औषधि लेखिएको छैन।" },
  "empty.referrals": { en: "No referrals.", ne: "कुनै रेफरल छैन।" },
  "empty.messages": { en: "No messages yet.", ne: "अहिलेसम्म कुनै सन्देश छैन।" },
  "empty.devices": { en: "No other devices.", ne: "अरू कुनै यन्त्र छैन।" },
  "messages.hours": { en: "Answered in working hours", ne: "कार्यालय समयमा जवाफ दिइन्छ" },
  "messages.notUrgent": { en: "This is not a way to get urgent help. If you are unwell now, go to the emergency department or call for an ambulance.", ne: "यो तुरुन्त सहायता पाउने माध्यम होइन। अहिले नै अस्वस्थ महसुस भइरहेको छ भने आपतकालीन विभागमा जानुहोस् वा एम्बुलेन्स बोलाउनुहोस्।" },
  "messages.ask": { en: "Ask something", ne: "केही सोध्नुहोस्" },
  "messages.about": { en: "What it is about", ne: "कुन विषयमा हो" },
  "profile.phone": { en: "Phone", ne: "फोन" },
  "profile.altPhone": { en: "Alternate phone", ne: "अर्को फोन" },
  "profile.email": { en: "Email", ne: "इमेल" },
  "profile.address": { en: "Current address", ne: "हालको ठेगाना" },
  "profile.emergency": { en: "Emergency contact", ne: "आपतकालीन सम्पर्क" },
  "correction.propose": { en: "Propose a correction", ne: "सच्याउन अनुरोध" },
  "correction.reviewed": { en: "Changes are reviewed and confirmed by desk staff before updating your medical record.", ne: "डेस्कका कर्मचारीले जाँचेर पुष्टि गरेपछि मात्र तपाईंको रेकर्डमा परिवर्तन हुन्छ।" },
  "correction.field": { en: "Field to correct", ne: "सच्याउनुपर्ने कुरा" },
  "correction.current": { en: "Current recorded: ", ne: "अहिले लेखिएको: " },
  "correction.none": { en: "None on file", ne: "केही लेखिएको छैन" },
  "correction.newValue": { en: "Proposed new value", ne: "नयाँ मान" },
  "correction.enterValue": { en: "Enter new value", ne: "नयाँ मान लेख्नुहोस्" },
  "correction.reason": { en: "Reason for change", ne: "किन परिवर्तन गर्ने" },
  "correction.reasonHint": { en: "e.g. Changed phone number, relocated to new residence", ne: "जस्तै: फोन नम्बर बदलियो, नयाँ ठाउँमा सरियो" },
  "field.phone": { en: "Phone number", ne: "फोन नम्बर" },
  "field.alternatePhone": { en: "Alternate phone", ne: "अर्को फोन" },
  "field.email": { en: "Email", ne: "इमेल" },
  "field.address": { en: "Current residence / address", ne: "हालको बसोबास / ठेगाना" },
  "field.tole": { en: "Tole / Street", ne: "टोल / सडक" },
  "field.municipality": { en: "Municipality", ne: "नगरपालिका" },
  "field.guardianName": { en: "Emergency contact name", ne: "आपतकालीन सम्पर्कको नाम" },
  "field.guardianPhone": { en: "Emergency contact phone", ne: "आपतकालीन सम्पर्कको फोन" },
  "field.guardianRelationship": { en: "Emergency contact relationship", ne: "आपतकालीन सम्पर्कसँगको नाता" },

  "results.discuss": { en: "Your doctor will go through this with you", ne: "तपाईंको डाक्टरले यसबारे तपाईंसँग कुरा गर्नुहुनेछ" },
  "results.usual": { en: "usual {range}", ne: "सामान्य {range}" },
  "results.report": { en: "Official report", ne: "आधिकारिक रिपोर्ट" },
  "results.withDoctor": { en: "The report is with your doctor.", ne: "रिपोर्ट तपाईंको डाक्टरसँग छ।" },
  "flag.low": { en: "Low", ne: "कम" },
  "flag.high": { en: "High", ne: "बढी" },
  "flag.critical_low": { en: "Very low", ne: "धेरै कम" },
  "flag.critical_high": { en: "Very high", ne: "धेरै बढी" },
  "flag.abnormal": { en: "Outside range", ne: "दायराभन्दा बाहिर" },

  "appointments.book": { en: "Book a visit", ne: "भेट बुक गर्नुहोस्" },
  "appointments.upcoming": { en: "Coming up", ne: "आउँदै गरेका" },
  "appointments.past": { en: "Past", ne: "विगतका" },
  "appointments.none": { en: "No appointments yet.", ne: "अहिलेसम्म कुनै भेट छैन।" },
  "appointments.cancel": { en: "Cancel this visit", ne: "यो भेट रद्द गर्नुहोस्" },
  "appointments.tooLate": {
    en: "Too close to cancel here — please ring the hospital if you cannot come.",
    ne: "यहाँबाट रद्द गर्न धेरै ढिलो भयो — आउन नसक्नुहुने भए अस्पतालमा फोन गर्नुहोस्।",
  },
  "appointments.confirmCancel": {
    en: "Cancel this visit? The time will be offered to somebody else.",
    ne: "यो भेट रद्द गर्ने? यो समय अरू कसैलाई दिइनेछ।",
  },
  "appointments.yesCancel": { en: "Yes, cancel", ne: "हो, रद्द गर्नुहोस्" },
  "appointments.keep": { en: "Keep it", ne: "राख्नुहोस्" },

  "booking.back": { en: "My appointments", ne: "मेरा भेटघाट" },
  "booking.title": { en: "Book a visit", ne: "भेट बुक गर्नुहोस्" },
  "booking.held": { en: "You have {n} of {limit} online bookings.", ne: "तपाईंसँग {limit} मध्ये {n} अनलाइन बुकिङ छ।" },
  "booking.limit": { en: "You can hold up to {limit} online bookings at a time.", ne: "एकपटकमा बढीमा {limit} वटा अनलाइन बुकिङ राख्न सकिन्छ।" },
  "booking.closed": { en: "closed", ne: "बन्द" },
  "booking.free": { en: "{n} free", ne: "{n} खाली" },
  "booking.morning": { en: "Morning", ne: "बिहान" },
  "booking.afternoon": { en: "Afternoon", ne: "दिउँसो" },
  "booking.noneThisDay": {
    en: "No online appointments on this day. Try another, or ring the hospital — some slots are kept for people who come in person.",
    ne: "यो दिन अनलाइन भेट उपलब्ध छैन। अर्को दिन हेर्नुहोस्, वा अस्पतालमा फोन गर्नुहोस् — केही समय आफैं आउनेहरूका लागि राखिन्छ।",
  },
  "booking.anotherTime": { en: "Choose another time", ne: "अर्को समय छान्नुहोस्" },
  "booking.yourVisit": { en: "Your visit", ne: "तपाईंको भेट" },
  "booking.minutes": { en: "About {n} minutes", ne: "करिब {n} मिनेट" },
  "booking.fee": { en: "Consultation fee, paid at the hospital", ne: "परामर्श शुल्क, अस्पतालमा तिर्ने" },
  "booking.reason": { en: "What is it about? (optional)", ne: "केका लागि? (ऐच्छिक)" },
  "booking.reasonHint": {
    en: "A few words help the doctor prepare — for example, a follow-up for blood pressure.",
    ne: "केही शब्दले डाक्टरलाई तयारी गर्न सहयोग गर्छ — जस्तै, रक्तचापको फलोअप।",
  },
  "booking.confirm": { en: "Confirm booking", ne: "बुकिङ पक्का गर्नुहोस्" },
  "booking.done": { en: "You are booked", ne: "तपाईंको भेट पक्का भयो" },
  "booking.before": { en: "Before you come", ne: "आउनुअघि" },
  "booking.early": {
    en: "Arrive 15 minutes early and show your hospital number at registration.",
    ne: "१५ मिनेट अगाडि आइपुग्नुहोस् र दर्तामा आफ्नो अस्पताल नम्बर देखाउनुहोस्।",
  },
  "booking.bring": { en: "Bring any reports and medicines you are taking.", ne: "आफ्ना रिपोर्ट र खाइरहेका औषधि लिएर आउनुहोस्।" },
  "booking.reference": { en: "Booking reference {ref}.", ne: "बुकिङ सन्दर्भ {ref}।" },
  "booking.ok": { en: "Done", ne: "ठीक छ" },
  "booking.at": { en: "{date} at {time}", ne: "{date}, {time}" },

  "common.back": { en: "Back", ne: "पछाडि" },
  "common.loadFailed": { en: "Could not load.", ne: "लोड हुन सकेन।" },
  "lang.switch": { en: "नेपाली", ne: "English" },
} as const;

export type StringKey = keyof typeof STRINGS;

/** How often, in the patient's language. Server labels stay the English fallback. */
const FREQUENCY_NE: Record<string, string> = {
  OD: "दिनको एक पटक",
  BD: "दिनको दुई पटक",
  TDS: "दिनको तीन पटक",
  QDS: "दिनको चार पटक",
  QID: "दिनको चार पटक",
  NOCTE: "राति",
  MANE: "बिहान",
  STAT: "तुरुन्त, एक पटक",
  PRN: "आवश्यक परेमा",
};

/**
 * Fill a string in the active language.
 *
 * Numbers passed as numbers are counts this app produced — "4 results",
 * "31 free" — and are written in Devanagari in Nepali, so they sit naturally
 * beside Nepali dates. Numbers passed as strings are things the hospital
 * prints and people read aloud or type — a hospital number, a bill total —
 * and are left exactly as they are.
 */
export function translate(key: StringKey, vars: Record<string, string | number> = {}): string {
  const entry = STRINGS[key];
  let text: string = entry ? entry[active] : key;
  for (const [name, value] of Object.entries(vars)) {
    const shown = typeof value === "number" && active === "ne" ? toNepaliDigits(String(value)) : String(value);
    text = text.split(`{${name}}`).join(shown);
  }
  return text;
}

/** "Female", "Male" — or "महिला", "पुरुष". A single letter is not Nepali. */
export function sexLabel(gender: string | undefined): string {
  if (!gender) return "";
  if (active === "ne") {
    return { female: "महिला", male: "पुरुष", other: "अन्य" }[gender] ?? "";
  }
  return gender.charAt(0).toUpperCase();
}

/**
 * "1 capsule, three times daily" in the patient's language. Built from the
 * structured fields rather than translated from the server's sentence, so a
 * Nepali reader gets "१ क्याप्सुल, दिनको तीन पटक" rather than half of each.
 */
export function directions(dose: string, frequencyCode: string, fallback: string, prnFor = ""): string {
  if (active !== "ne" || !FREQUENCY_NE[frequencyCode]) return fallback;
  const often = FREQUENCY_NE[frequencyCode] + (prnFor ? ` (${prnFor})` : "");
  return [dose, often].filter(Boolean).join(", ");
}

// ---------------------------------------------------------------------------
// Dates
// ---------------------------------------------------------------------------

const NEPALI_DIGITS = "०१२३४५६७८९";
const toNepaliDigits = (text: string) => text.replace(/\d/g, (digit) => NEPALI_DIGITS[Number(digit)]);

function asDate(value: string | Date): Date {
  return value instanceof Date ? value : new Date(value);
}

/** A date: "12 Sep 2026", or "२७ भाद्र २०८३". */
export function formatDate(value: string | Date | null | undefined): string {
  if (!value) return "—";
  const date = asDate(value);
  if (active === "ne") {
    return new NepaliDate(date).format("DD MMMM YYYY", "np");
  }
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

/** A weekday and date: "Sunday 13 September", or "आइतबार, २८ भाद्र". */
export function formatLongDate(value: string | Date): string {
  const date = asDate(value);
  if (active === "ne") {
    return new NepaliDate(date).format("ddd, DD MMMM", "np");
  }
  return date.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });
}

/**
 * A clock time: "10:20 am", or "बिहान १०:२०". `bare` drops the part of the
 * day — for a list already grouped under "बिहान" and "दिउँसो", where saying it
 * again on every chip is noise.
 */
export function formatTime(value: string | Date, bare = false): string {
  const date = asDate(value);
  if (active === "ne") {
    const hours = date.getHours();
    const period = hours < 12 ? "बिहान" : hours < 17 ? "दिउँसो" : "बेलुकी";
    const twelve = ((hours + 11) % 12) + 1;
    const clock = toNepaliDigits(`${twelve}:${String(date.getMinutes()).padStart(2, "0")}`);
    return bare ? clock : `${period} ${clock}`;
  }
  const clock = date.toLocaleTimeString("en-GB", { hour: "numeric", minute: "2-digit", hour12: true });
  return bare ? clock.replace(/\s?[ap]m$/i, "") : clock;
}

export function formatDateTime(value: string | Date | null | undefined): string {
  if (!value) return "—";
  return `${formatDate(value)}, ${formatTime(value)}`;
}

/** The parts a calendar leaf shows: month name and day, in the active calendar. */
export function dateLeaf(value: string | Date): { month: string; day: string; weekday: string } {
  const date = asDate(value);
  if (active === "ne") {
    const nepali = new NepaliDate(date);
    return {
      month: nepali.format("MMMM", "np"),
      day: nepali.format("DD", "np").replace(/^०/, ""),
      weekday: nepali.format("ddd", "np"),
    };
  }
  return {
    month: date.toLocaleDateString("en-GB", { month: "short" }),
    day: String(date.getDate()),
    weekday: date.toLocaleDateString("en-GB", { weekday: "short" }),
  };
}

// ---------------------------------------------------------------------------
// React
// ---------------------------------------------------------------------------

interface I18n {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: typeof translate;
}

const Context = createContext<I18n>({ lang: active, setLang: () => undefined, t: translate });

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setState] = useState<Lang>(active);

  const setLang = useCallback((next: Lang) => {
    active = next;
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* the choice still holds for this visit */
    }
    document.documentElement.lang = next;
    setState(next);
  }, []);

  // `t` changes identity with the language so memoised children re-render.
  const value = useMemo(
    () => ({ lang, setLang, t: ((key, vars) => translate(key, vars)) as typeof translate }),
    [lang, setLang],
  );
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useI18n(): I18n {
  return useContext(Context);
}

/** The switch: shows the other language's name, in that language. */
export function LanguageSwitch({ className = "" }: { className?: string }) {
  const { lang, setLang, t } = useI18n();
  return (
    <button
      type="button"
      onClick={() => setLang(lang === "en" ? "ne" : "en")}
      className={`rounded-full border px-3 py-1 text-sm font-medium transition-colors hover:bg-muted ${className}`}
      lang={lang === "en" ? "ne" : "en"}
    >
      {t("lang.switch")}
    </button>
  );
}
