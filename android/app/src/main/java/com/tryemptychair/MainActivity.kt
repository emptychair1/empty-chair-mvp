package com.tryemptychair

import android.Manifest
import android.content.ContentUris
import android.content.ContentValues
import android.content.pm.PackageManager
import android.os.Bundle
import android.provider.CalendarContract
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.biometric.BiometricPrompt
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.KeyboardOptions
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import androidx.lifecycle.lifecycleScope
import androidx.work.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.time.Instant
import java.util.concurrent.TimeUnit

class MainActivity : FragmentActivity() {
    private val amber=Color(0xFFFFB000); private val bg=Color(0xFF0B0905)
    private var unlocked by mutableStateOf(false)
    private var linked by mutableStateOf(false)
    private var permission by mutableStateOf(false)
    private var calendars by mutableStateOf(listOf<CalendarRow>())
    private var selected by mutableStateOf<Long?>(null)
    private var phone by mutableStateOf("")
    private var code by mutableStateOf("")
    private var challenge by mutableStateOf<String?>(null)
    private var message by mutableStateOf("")
    private var status by mutableStateOf("LOCKED")
    private val prefs by lazy { getSharedPreferences("empty_chair", MODE_PRIVATE) }

    private val calendarPermission=registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { result ->
        permission=result[Manifest.permission.READ_CALENDAR]==true && result[Manifest.permission.WRITE_CALENDAR]==true
        if(permission){loadCalendars();status=if(selected==null) "CHOOSE CALENDAR" else "ARMED";scheduleSync()}
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        linked=!prefs.getString("device_token",null).isNullOrBlank()
        selected=prefs.getLong("calendar_id",-1L).takeIf{it>=0}
        permission=ContextCompat.checkSelfPermission(this,Manifest.permission.READ_CALENDAR)==PackageManager.PERMISSION_GRANTED && ContextCompat.checkSelfPermission(this,Manifest.permission.WRITE_CALENDAR)==PackageManager.PERMISSION_GRANTED
        if(permission) loadCalendars()
        setContent { MaterialTheme { Surface(Modifier.fillMaxSize().background(bg),color=bg){Screen()} } }
        unlock()
    }

    private fun unlock(){
        val executor=ContextCompat.getMainExecutor(this)
        val prompt=BiometricPrompt(this,executor,object:BiometricPrompt.AuthenticationCallback(){
            override fun onAuthenticationSucceeded(result:BiometricPrompt.AuthenticationResult){unlocked=true;status="READY"}
            override fun onAuthenticationError(errorCode:Int,errString:CharSequence){if(errorCode==BiometricPrompt.ERROR_NO_BIOMETRICS||errorCode==BiometricPrompt.ERROR_HW_NOT_PRESENT){unlocked=true}else status="LOCKED"}
        })
        val info=BiometricPrompt.PromptInfo.Builder().setTitle("EMPTY CHAIR").setSubtitle("Unlock Empty Chair").setAllowedAuthenticators(androidx.biometric.BiometricManager.Authenticators.BIOMETRIC_STRONG or androidx.biometric.BiometricManager.Authenticators.DEVICE_CREDENTIAL).build()
        prompt.authenticate(info)
    }

    @Composable private fun Screen(){
        Column(Modifier.fillMaxSize().padding(24.dp),verticalArrangement=Arrangement.spacedBy(20.dp)){
            Text("EMPTY CHAIR                                      2.0",color=amber,fontFamily=FontFamily.Monospace)
            when {
                !unlocked -> {Text("EMPTY CHAIR // LOCKED",color=amber,fontFamily=FontFamily.Monospace,style=MaterialTheme.typography.headlineLarge);Button(onClick={unlock()}){Text("UNLOCK")}}
                !linked -> {
                    Text("LINK THIS PHONE",color=amber,fontFamily=FontFamily.Monospace,style=MaterialTheme.typography.headlineMedium)
                    if(challenge==null){OutlinedTextField(phone,{phone=it},label={Text("MOBILE")},keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Phone));Button(onClick={startLink()}){Text("TEXT ME A CODE")}}
                    else {Text(message,color=amber,fontFamily=FontFamily.Monospace);OutlinedTextField(code,{code=it},label={Text("6-DIGIT CODE")},keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Number));Button(onClick={verifyLink()}){Text("VERIFY THIS PHONE")}}
                }
                !permission -> {Text("WHERE DO YOUR APPOINTMENTS LIVE?",color=amber,fontFamily=FontFamily.Monospace);Button(onClick={calendarPermission.launch(arrayOf(Manifest.permission.READ_CALENDAR,Manifest.permission.WRITE_CALENDAR))}){Text("[ A ] ANDROID CALENDAR")}}
                selected==null -> {Text("WHICH ONE HOLDS TATTOOS?",color=amber,fontFamily=FontFamily.Monospace);calendars.forEach{c->Button(onClick={selected=c.id;prefs.edit().putLong("calendar_id",c.id).apply();status="ARMED";scheduleSync();syncNow()}){Text(c.name.uppercase())}}}
                else -> {Spacer(Modifier.weight(1f));Text(if(status=="CHECK CALENDAR") "CHECK CALENDAR" else "ARMED. ✓",color=amber,fontFamily=FontFamily.Monospace,style=MaterialTheme.typography.displayMedium);Text(if(status=="CHECK CALENDAR") "calendar.................[!]" else "calendar................[✓]\n\nYOU CAN CLOSE THIS NOW.",color=amber,fontFamily=FontFamily.Monospace);Spacer(Modifier.weight(1f))}
            }
        }
    }

    private fun startLink(){lifecycleScope.launch(Dispatchers.IO){try{val r=post("/native/auth/start",JSONObject().put("phone",phone).put("platform","android"),null);withContext(Dispatchers.Main){challenge=r.getString("challenge_id");message="CODE SENT TO ***${r.getString("last4")}"}}catch(_:Exception){withContext(Dispatchers.Main){message="CHECK THAT MOBILE NUMBER"}}}}
    private fun verifyLink(){val ch=challenge?:return;lifecycleScope.launch(Dispatchers.IO){try{val r=post("/native/auth/verify",JSONObject().put("challenge_id",ch).put("code",code).put("calendar_id",selected?.toString()?:"").put("platform","android"),null);prefs.edit().putString("device_token",r.getString("device_token")).apply();withContext(Dispatchers.Main){linked=true;message="LINKED [✓]"}}catch(_:Exception){withContext(Dispatchers.Main){message="THAT CODE DIDN'T WORK"}}}}

    private fun loadCalendars(){val out=mutableListOf<CalendarRow>();contentResolver.query(CalendarContract.Calendars.CONTENT_URI,arrayOf(CalendarContract.Calendars._ID,CalendarContract.Calendars.CALENDAR_DISPLAY_NAME),"${CalendarContract.Calendars.VISIBLE}=1",null,null)?.use{c->while(c.moveToNext())out+=CalendarRow(c.getLong(0),c.getString(1)?:"Calendar")};calendars=out}
    private fun syncNow(){val token=prefs.getString("device_token",null)?:return;val calendarId=selected?:return;lifecycleScope.launch(Dispatchers.IO){try{NativeCalendarSync.sync(this@MainActivity,calendarId,token);withContext(Dispatchers.Main){status="ARMED"}}catch(_:Exception){withContext(Dispatchers.Main){status="CHECK CALENDAR"}}}}
    private fun scheduleSync(){if(!linked||!permission||selected==null)return;val request=PeriodicWorkRequestBuilder<CalendarSyncWorker>(15,TimeUnit.MINUTES).setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build();WorkManager.getInstance(this).enqueueUniquePeriodicWork("empty-chair-calendar",ExistingPeriodicWorkPolicy.UPDATE,request)}

    companion object { fun post(path:String,payload:JSONObject,token:String?):JSONObject{val c=URL("https://app.tryemptychair.com$path").openConnection() as HttpURLConnection;c.requestMethod="POST";c.setRequestProperty("Content-Type","application/json");if(token!=null)c.setRequestProperty("Authorization","Bearer $token");c.doOutput=true;c.outputStream.use{it.write(payload.toString().toByteArray())};if(c.responseCode !in 200..299)throw IllegalStateException("HTTP ${c.responseCode}");return JSONObject(c.inputStream.bufferedReader().readText())} }
}

data class CalendarRow(val id:Long,val name:String)

object NativeCalendarSync {
    fun sync(context:android.content.Context,calendarId:Long,token:String){
        val now=System.currentTimeMillis();val end=now+180L*86400000L;val events=JSONArray();val uri=CalendarContract.Instances.CONTENT_URI.buildUpon();ContentUris.appendId(uri,now-86400000L);ContentUris.appendId(uri,end)
        context.contentResolver.query(uri.build(),arrayOf(CalendarContract.Instances.EVENT_ID,CalendarContract.Instances.TITLE,CalendarContract.Instances.BEGIN,CalendarContract.Instances.END),"${CalendarContract.Instances.CALENDAR_ID}=?",arrayOf(calendarId.toString()),null)?.use{c->while(c.moveToNext())events.put(JSONObject().put("id",c.getLong(0).toString()).put("title",c.getString(1)?:"Tattoo").put("start_at",Instant.ofEpochMilli(c.getLong(2)).toString()).put("end_at",Instant.ofEpochMilli(c.getLong(3)).toString()))}
        val reply=MainActivity.post("/native/calendar/sync",JSONObject().put("calendar_id",calendarId.toString()).put("events",events),token);val commands=reply.optJSONArray("commands")?:JSONArray();for(i in 0 until commands.length()){val command=commands.getJSONObject(i);if(command.optString("kind")!="upsert_event")continue;val p=command.getJSONObject("payload");val values=ContentValues().apply{put(CalendarContract.Events.CALENDAR_ID,calendarId);put(CalendarContract.Events.TITLE,p.getString("title"));put(CalendarContract.Events.DESCRIPTION,p.optString("notes"));put(CalendarContract.Events.DTSTART,Instant.parse(p.getString("start_at")).toEpochMilli());put(CalendarContract.Events.DTEND,Instant.parse(p.getString("end_at")).toEpochMilli());put(CalendarContract.Events.EVENT_TIMEZONE,"UTC")};context.contentResolver.insert(CalendarContract.Events.CONTENT_URI,values);MainActivity.post("/native/calendar/ack/${command.getString("id")}",JSONObject(),token)}
    }
}

class CalendarSyncWorker(context:android.content.Context,params:WorkerParameters):Worker(context,params){override fun doWork():Result{val prefs=applicationContext.getSharedPreferences("empty_chair",android.content.Context.MODE_PRIVATE);val token=prefs.getString("device_token",null)?:return Result.success();val id=prefs.getLong("calendar_id",-1L);if(id<0)return Result.success();return try{NativeCalendarSync.sync(applicationContext,id,token);Result.success()}catch(_:Exception){Result.retry()}}}
