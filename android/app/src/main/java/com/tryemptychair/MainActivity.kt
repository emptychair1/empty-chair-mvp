package com.tryemptychair

import android.Manifest
import android.content.ContentUris
import android.content.ContentValues
import android.content.pm.PackageManager
import android.os.Bundle
import android.provider.CalendarContract
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.time.Instant

class MainActivity : ComponentActivity() {
    private val amber=Color(0xFFFFB000); private val bg=Color(0xFF0B0905)
    private var permission by mutableStateOf(false)
    private var calendars by mutableStateOf(listOf<CalendarRow>())
    private var selected by mutableStateOf<Long?>(null)
    private var status by mutableStateOf("LOCKED")
    private val prefs by lazy { getSharedPreferences("empty_chair", MODE_PRIVATE) }

    private val calendarPermission=registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { result ->
        permission=result[Manifest.permission.READ_CALENDAR]==true && result[Manifest.permission.WRITE_CALENDAR]==true
        if(permission){loadCalendars();status=if(selected==null) "CHOOSE CALENDAR" else "ARMED"}
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        selected=prefs.getLong("calendar_id",-1L).takeIf{it>=0}
        permission=ContextCompat.checkSelfPermission(this,Manifest.permission.READ_CALENDAR)==PackageManager.PERMISSION_GRANTED && ContextCompat.checkSelfPermission(this,Manifest.permission.WRITE_CALENDAR)==PackageManager.PERMISSION_GRANTED
        if(permission) loadCalendars()
        setContent { MaterialTheme { Surface(Modifier.fillMaxSize().background(bg),color=bg){Screen()} } }
    }

    @Composable private fun Screen(){
        Column(Modifier.fillMaxSize().padding(24.dp),verticalArrangement=Arrangement.spacedBy(20.dp)){
            Text("EMPTY CHAIR                                      2.0",color=amber,fontFamily=FontFamily.Monospace)
            when {
                !permission -> {Text("WHERE DO YOUR APPOINTMENTS LIVE?",color=amber,fontFamily=FontFamily.Monospace);Button(onClick={calendarPermission.launch(arrayOf(Manifest.permission.READ_CALENDAR,Manifest.permission.WRITE_CALENDAR))}){Text("[ A ] ANDROID CALENDAR")}}
                selected==null -> {Text("WHICH ONE HOLDS TATTOOS?",color=amber,fontFamily=FontFamily.Monospace);calendars.forEach{c->Button(onClick={selected=c.id;prefs.edit().putLong("calendar_id",c.id).apply();status="ARMED";sync()}){Text(c.name.uppercase())}}}
                else -> {Spacer(Modifier.weight(1f));Text("ARMED. ✓",color=amber,fontFamily=FontFamily.Monospace,style=MaterialTheme.typography.displayMedium);Text("calendar................[✓]\n\nYOU CAN CLOSE THIS NOW.",color=amber,fontFamily=FontFamily.Monospace);Spacer(Modifier.weight(1f))}
            }
        }
    }

    private fun loadCalendars(){
        val out=mutableListOf<CalendarRow>(); val projection=arrayOf(CalendarContract.Calendars._ID,CalendarContract.Calendars.CALENDAR_DISPLAY_NAME)
        contentResolver.query(CalendarContract.Calendars.CONTENT_URI,projection,"${CalendarContract.Calendars.VISIBLE}=1",null,null)?.use{c->while(c.moveToNext())out+=CalendarRow(c.getLong(0),c.getString(1)?:"Calendar")};calendars=out
    }

    private fun sync(){
        val calendarId=selected?:return; val token=prefs.getString("device_token",null)?:return
        lifecycleScope.launch(Dispatchers.IO){
            try{
                val now=System.currentTimeMillis(); val end=now+180L*86400000L; val events=JSONArray()
                val uri=CalendarContract.Instances.CONTENT_URI.buildUpon();ContentUris.appendId(uri,now-86400000L);ContentUris.appendId(uri,end)
                contentResolver.query(uri.build(),arrayOf(CalendarContract.Instances.EVENT_ID,CalendarContract.Instances.TITLE,CalendarContract.Instances.BEGIN,CalendarContract.Instances.END),"${CalendarContract.Instances.CALENDAR_ID}=?",arrayOf(calendarId.toString()),null)?.use{c->while(c.moveToNext()){events.put(JSONObject().put("id",c.getLong(0).toString()).put("title",c.getString(1)?:"Tattoo").put("start_at",Instant.ofEpochMilli(c.getLong(2)).toString()).put("end_at",Instant.ofEpochMilli(c.getLong(3)).toString()))}}
                val payload=JSONObject().put("calendar_id",calendarId.toString()).put("events",events)
                val reply=post("/native/calendar/sync",payload,token)
                val commands=reply.optJSONArray("commands")?:JSONArray();for(i in 0 until commands.length()){val command=commands.getJSONObject(i);if(command.optString("kind")=="upsert_event")applyCommand(calendarId,command,token)}
            }catch(_:Exception){withContext(Dispatchers.Main){status="CHECK CALENDAR"}}
        }
    }

    private fun applyCommand(calendarId:Long,command:JSONObject,token:String){
        val p=command.getJSONObject("payload");val values=ContentValues().apply{put(CalendarContract.Events.CALENDAR_ID,calendarId);put(CalendarContract.Events.TITLE,p.getString("title"));put(CalendarContract.Events.DESCRIPTION,p.optString("notes"));put(CalendarContract.Events.DTSTART,Instant.parse(p.getString("start_at")).toEpochMilli());put(CalendarContract.Events.DTEND,Instant.parse(p.getString("end_at")).toEpochMilli());put(CalendarContract.Events.EVENT_TIMEZONE,"UTC")};contentResolver.insert(CalendarContract.Events.CONTENT_URI,values);post("/native/calendar/ack/${command.getString("id")}",JSONObject(),token)
    }

    private fun post(path:String,payload:JSONObject,token:String):JSONObject{
        val c=URL("https://app.tryemptychair.com$path").openConnection() as HttpURLConnection;c.requestMethod="POST";c.setRequestProperty("Content-Type","application/json");c.setRequestProperty("Authorization","Bearer $token");c.doOutput=true;c.outputStream.use{it.write(payload.toString().toByteArray())};if(c.responseCode !in 200..299)throw IllegalStateException("HTTP ${c.responseCode}");return JSONObject(c.inputStream.bufferedReader().readText())
    }
}
data class CalendarRow(val id:Long,val name:String)
