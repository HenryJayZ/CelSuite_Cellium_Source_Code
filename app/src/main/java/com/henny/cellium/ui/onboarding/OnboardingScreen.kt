package com.henny.cellium.ui.onboarding

import androidx.compose.animation.AnimatedContent
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowForward
import androidx.compose.material.icons.rounded.ArrowDropDown
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.CloudSync
import androidx.compose.material.icons.rounded.Gavel
import androidx.compose.material.icons.rounded.Key
import androidx.compose.material.icons.rounded.Memory
import androidx.compose.material.icons.rounded.Person
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material.icons.rounded.Visibility
import androidx.compose.material.icons.rounded.VisibilityOff
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.henny.cellium.R
import com.henny.cellium.ai.ProviderCatalog
import com.henny.cellium.ai.ProviderPresets
import com.henny.cellium.avatar.AVATAR_GENDERS
import com.henny.cellium.avatar.AvatarLibrary
import com.henny.cellium.avatar.DotMatrixAvatarCanvas
import com.henny.cellium.data.local.ProviderProfileEntity
import com.henny.cellium.ui.chat.ProviderSearchDropdownSheet
import com.henny.cellium.ui.components.CelliumBackground
import com.henny.cellium.ui.components.GlassCard
import com.henny.cellium.ui.components.VectorBadgeIcon
import com.henny.cellium.ui.theme.CelBorderSubtle
import com.henny.cellium.ui.theme.CelDangerRed
import com.henny.cellium.ui.theme.CelEmeraldThought
import com.henny.cellium.ui.theme.CelLavender
import com.henny.cellium.ui.theme.CelTerminalBg
import com.henny.cellium.ui.theme.CelTextMuted
import com.henny.cellium.ui.theme.CelTextPrimary
import com.henny.cellium.ui.theme.CelTextSecondary
import com.henny.cellium.ui.theme.JetBrainsMono
import com.henny.cellium.ui.theme.LocalCelliumVisuals
import kotlinx.coroutines.launch

@Composable
fun OnboardingScreen(
    providers: List<ProviderProfileEntity>,
    initialTermsAccepted: Boolean,
    initialAvatarGender: String = "Chibi",
    googleAuthBusy: Boolean,
    googleAuthError: String?,
    signedInEmail: String?,
    onAcceptTerms: () -> Unit,
    onContinueAsGuest: () -> Unit,
    onContinueWithGoogle: () -> Unit,
    onSelectAvatarGender: (String) -> Unit = {},
    onSaveProviderConfig: suspend (ProviderProfileEntity) -> Unit,
    onFetchModels: suspend (ProviderProfileEntity) -> Result<List<String>>,
    onCompleteOnboarding: (selectedProviderId: String) -> Unit,
) {
    val visuals = LocalCelliumVisuals.current
    var step by remember { mutableIntStateOf(if (initialTermsAccepted) 1 else 0) }
    var chosenAvatarGender by remember(initialAvatarGender) { mutableStateOf(initialAvatarGender.ifBlank { "Chibi" }) }

    CelliumBackground(dimAlpha = 0.56f) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .statusBarsPadding()
                .navigationBarsPadding()
                .padding(horizontal = 20.dp, vertical = 14.dp),
            contentAlignment = Alignment.Center,
        ) {
            Column(
                modifier = Modifier
                    .widthIn(max = 560.dp)
                    .fillMaxSize(),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        Image(
                            painter = painterResource(id = R.drawable.ic_cellium_brand),
                            contentDescription = "Cel.Cellium logo",
                            modifier = Modifier
                                .size(38.dp)
                                .clip(CircleShape)
                                .border(1.2.dp, visuals.activeBorder, CircleShape),
                        )
                        Column {
                            Text(
                                text = "Cel.Cellium",
                                style = MaterialTheme.typography.titleLarge,
                                color = CelTextPrimary,
                            )
                            Text(
                                text = "${com.henny.cellium.BuildConfig.VERSION_NAME} · Step ${step + 1} of 4",
                                style = MaterialTheme.typography.labelSmall,
                                color = CelLavender,
                            )
                        }
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        repeat(4) { idx ->
                            Box(
                                modifier = Modifier
                                    .width(if (idx == step) 26.dp else 10.dp)
                                    .height(6.dp)
                                    .clip(RoundedCornerShape(99.dp))
                                    .background(if (idx <= step) visuals.primary else CelBorderSubtle)
                            )
                        }
                    }
                }

                Spacer(Modifier.height(16.dp))

                AnimatedContent(
                    targetState = step,
                    modifier = Modifier.weight(1f).fillMaxWidth(),
                    label = "onboarding_step",
                ) { currentStep ->
                    when (currentStep) {
                        0 -> TermsStep(
                            onAccepted = {
                                onAcceptTerms()
                                step = 1
                            },
                        )
                        1 -> ProfileChoiceStep(
                            googleAuthBusy = googleAuthBusy,
                            googleAuthError = googleAuthError,
                            signedInEmail = signedInEmail,
                            onGuest = {
                                onContinueAsGuest()
                                step = 2
                            },
                            onGoogle = { onContinueWithGoogle() },
                            onContinueAfterGoogle = { step = 2 },
                        )
                        2 -> ChooseAvatarStyleStep(
                            selectedGender = chosenAvatarGender,
                            onSelectGender = { g ->
                                chosenAvatarGender = g
                                onSelectAvatarGender(g)
                            },
                            onContinue = {
                                onSelectAvatarGender(chosenAvatarGender)
                                step = 3
                            },
                        )
                        else -> StartupProviderStep(
                            providers = providers,
                            onSaveProviderConfig = onSaveProviderConfig,
                            onFetchModels = onFetchModels,
                            onFinish = onCompleteOnboarding,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun TermsStep(onAccepted: () -> Unit) {
    val visuals = LocalCelliumVisuals.current
    var checked by remember { mutableStateOf(false) }

    GlassCard(
        modifier = Modifier.fillMaxSize(),
        highlighted = true,
        shape = RoundedCornerShape(24.dp),
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Icon(Icons.Rounded.Gavel, contentDescription = null, tint = visuals.primary)
            Column {
                Text(
                    text = "Terms & Conditions",
                    style = MaterialTheme.typography.titleLarge,
                    color = CelTextPrimary,
                )
                Text(
                    text = "Cel.Cellium Local-First Companion Agreement",
                    style = MaterialTheme.typography.labelMedium,
                    color = CelTextSecondary,
                )
            }
        }

        Spacer(Modifier.height(12.dp))

        Column(
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth()
                .clip(RoundedCornerShape(14.dp))
                .background(CelTerminalBg.copy(alpha = 0.78f))
                .border(1.dp, CelBorderSubtle, RoundedCornerShape(14.dp))
                .verticalScroll(rememberScrollState())
                .padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            TermsBlock(
                "1. Bring Your Own Keys (200+ Providers), Free Testing & Offline AI",
                "Cel.Cellium is a universal AI workspace supporting 200+ cloud providers, instant keyless free testing via Pollinations AI, and 100% offline on-device .gguf (llama.cpp) and .task/.bin (MediaPipe) models. Cel.Cellium never locks you into one provider.",
            )
            TermsBlock(
                "2. Local-First Storage & Private Google Account Sync",
                "All chats, branches, Arena group chats, personas, memories, stats, generated artwork, Kaggle credentials, and API keys are stored locally in your device's Room SQLite database. If you sign in with Google, your API keys, Kaggle credentials, stats, settings, chats, templates, personas, and memories are backed up privately to your own Google account.",
            )
            TermsBlock(
                "3. Shizuku Privilege & Agent Mode Safety",
                "Optional Shizuku integration provides >1.5 GB RAM anti-kill protection for heavy on-device models and AI Agent shell commands. Destructive patterns are blocked by Command Guard, and mutating commands require your explicit approval.",
            )
            TermsBlock(
                "4. User Responsibility",
                "You are responsible for usage quotas, billing, and content policies of any third-party AI provider you configure, as well as any shell command you approve in Agent Mode.",
            )
        }

        Spacer(Modifier.height(12.dp))

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(12.dp))
                .clickable { checked = !checked }
                .padding(vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Checkbox(
                checked = checked,
                onCheckedChange = { checked = it },
                colors = CheckboxDefaults.colors(checkedColor = visuals.primary),
                modifier = Modifier.testTag("terms_checkbox"),
            )
            Text(
                text = "I have read and accept the Cel.Cellium Terms & Conditions.",
                style = MaterialTheme.typography.bodySmall,
                color = CelTextPrimary,
            )
        }

        Spacer(Modifier.height(10.dp))

        Button(
            onClick = onAccepted,
            enabled = checked,
            modifier = Modifier
                .fillMaxWidth()
                .height(52.dp)
                .testTag("terms_accept_button"),
            shape = RoundedCornerShape(16.dp),
            colors = ButtonDefaults.buttonColors(containerColor = visuals.primary),
        ) {
            Text("Accept & Continue", style = MaterialTheme.typography.titleSmall)
            Spacer(Modifier.width(8.dp))
            Icon(Icons.AutoMirrored.Rounded.ArrowForward, contentDescription = null, modifier = Modifier.size(18.dp))
        }
    }
}

@Composable
private fun TermsBlock(title: String, body: String) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(text = title, style = MaterialTheme.typography.titleSmall, color = CelLavender)
        Text(text = body, style = MaterialTheme.typography.bodySmall, color = CelTextSecondary)
    }
}

@Composable
private fun ProfileChoiceStep(
    googleAuthBusy: Boolean,
    googleAuthError: String?,
    signedInEmail: String?,
    onGuest: () -> Unit,
    onGoogle: () -> Unit,
    onContinueAfterGoogle: () -> Unit,
) {
    val visuals = LocalCelliumVisuals.current

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        GlassCard(highlighted = true, shape = RoundedCornerShape(24.dp)) {
            Text(
                text = "How would you like to use Cel.Cellium?",
                style = MaterialTheme.typography.titleLarge,
                color = CelTextPrimary,
            )
            Spacer(Modifier.height(6.dp))
            Text(
                text = "Everything works 100% locally in Guest Mode. Google Sign-In is completely optional if you want private cloud backup for your API keys, stats, settings, chats, personas, and memories.",
                style = MaterialTheme.typography.bodyMedium,
                color = CelTextSecondary,
            )
        }

        GlassCard(highlighted = true, shape = RoundedCornerShape(22.dp)) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Box(
                    modifier = Modifier
                        .size(44.dp)
                        .clip(CircleShape)
                        .background(Brush.linearGradient(listOf(visuals.primary, visuals.secondary))),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(Icons.Rounded.Person, contentDescription = null, tint = Color.White)
                }
                Column(modifier = Modifier.weight(1f)) {
                    Text("Continue as Guest", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary)
                    Text(
                        "Instant local Room SQLite storage · Zero login required · Full 200+ BYOK, .gguf Offline AI & Shizuku",
                        style = MaterialTheme.typography.bodySmall,
                        color = CelTextSecondary,
                    )
                }
            }
            Spacer(Modifier.height(14.dp))
            Button(
                onClick = onGuest,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(50.dp)
                    .testTag("continue_as_guest_button"),
                shape = RoundedCornerShape(14.dp),
                colors = ButtonDefaults.buttonColors(containerColor = visuals.primary),
            ) {
                Text("Continue as Guest", fontWeight = FontWeight.SemiBold)
            }
        }

        GlassCard(shape = RoundedCornerShape(22.dp)) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Box(
                    modifier = Modifier
                        .size(44.dp)
                        .clip(CircleShape)
                        .background(CelTerminalBg)
                        .border(1.dp, visuals.subtleBorder, CircleShape),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(Icons.Rounded.CloudSync, contentDescription = null, tint = visuals.tertiary)
                }
                Column(modifier = Modifier.weight(1f)) {
                    Text("Optional Google Cloud Sync", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary)
                    Text(
                        "Privately backs up all your API keys, Kaggle credentials, stats, settings, chats, templates, personas & memories to your Google account.",
                        style = MaterialTheme.typography.bodySmall,
                        color = CelTextSecondary,
                    )
                }
            }

            if (googleAuthError != null) {
                Spacer(Modifier.height(8.dp))
                Text(text = googleAuthError, style = MaterialTheme.typography.bodySmall, color = CelDangerRed)
            }

            Spacer(Modifier.height(14.dp))

            if (signedInEmail != null) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Icon(Icons.Rounded.CheckCircle, contentDescription = null, tint = CelEmeraldThought, modifier = Modifier.size(18.dp))
                    Text("Signed in as $signedInEmail", style = MaterialTheme.typography.bodySmall, color = CelEmeraldThought)
                }
                Spacer(Modifier.height(10.dp))
                Button(
                    onClick = onContinueAfterGoogle,
                    modifier = Modifier.fillMaxWidth().height(48.dp),
                    shape = RoundedCornerShape(14.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = CelEmeraldThought),
                ) {
                    Text("Continue to Provider Setup", color = Color(0xFF042214), fontWeight = FontWeight.Bold)
                }
            } else {
                OutlinedButton(
                    onClick = onGoogle,
                    enabled = !googleAuthBusy,
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(48.dp)
                        .testTag("continue_with_google_button"),
                    shape = RoundedCornerShape(14.dp),
                ) {
                    if (googleAuthBusy) {
                        CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                        Spacer(Modifier.width(8.dp))
                        Text("Signing in...")
                    } else {
                        Text("Continue with Google (Optional)")
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ChooseAvatarStyleStep(
    selectedGender: String,
    onSelectGender: (String) -> Unit,
    onContinue: () -> Unit,
) {
    val visuals = LocalCelliumVisuals.current
    val context = LocalContext.current
    val library = remember(context) { AvatarLibrary.load(context) }

    val chibiExpr = remember(library) { library.get("Chibi", "Happy") ?: library.getForMood("Chibi", "happy") }
    val detailedExpr = remember(library) {
        library.get("Detailed Female", "Happy") ?: library.getForMood("Detailed Female", "happy")
    }
    val previewExpr = remember(library, selectedGender) {
        library.get(selectedGender, "Happy") ?: library.getForMood(selectedGender, "happy")
    }
    var blinkCount by remember { mutableIntStateOf(0) }

    GlassCard(
        modifier = Modifier.fillMaxSize(),
        highlighted = true,
        shape = RoundedCornerShape(24.dp),
    ) {
        Column(
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth()
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                text = "Choose Your Cel",
                style = MaterialTheme.typography.titleLarge,
                color = CelTextPrimary,
            )
            Text(
                text = "Pick how Cel's dot-matrix face looks in Live Mode, Floating Cel, and Assistant pop-ups. You can switch anytime in Avatar Studio.",
                style = MaterialTheme.typography.bodySmall,
                color = CelTextSecondary,
            )

            // Side-by-side animated comparison: Chibi (Default) vs Detailed
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                val chibiSelected = selectedGender == "Chibi"
                val detailedSelected = selectedGender.startsWith("Detailed")

                Column(
                    modifier = Modifier
                        .weight(1f)
                        .clip(RoundedCornerShape(18.dp))
                        .background(if (chibiSelected) visuals.primary.copy(alpha = 0.22f) else CelTerminalBg.copy(alpha = 0.84f))
                        .border(
                            width = if (chibiSelected) 1.6.dp else 1.dp,
                            color = if (chibiSelected) visuals.primary else CelBorderSubtle,
                            shape = RoundedCornerShape(18.dp),
                        )
                        .clickable {
                            onSelectGender("Chibi")
                            blinkCount++
                        }
                        .padding(10.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(112.dp)
                            .clip(RoundedCornerShape(12.dp))
                            .background(Color.Black),
                    ) {
                        DotMatrixAvatarCanvas(
                            expression = chibiExpr,
                            modifier = Modifier.fillMaxSize(),
                            scale = 0.92f,
                            blinkTrigger = if (chibiSelected) blinkCount else 0,
                            onTapped = {
                                onSelectGender("Chibi")
                                blinkCount++
                            },
                        )
                    }
                    Text(
                        text = "Chibi Cel",
                        style = MaterialTheme.typography.titleSmall,
                        color = if (chibiSelected) visuals.primary else CelTextPrimary,
                    )
                    Text(
                        text = "Default · Expressive & cute",
                        style = MaterialTheme.typography.labelSmall,
                        color = CelEmeraldThought,
                        textAlign = TextAlign.Center,
                    )
                }

                Column(
                    modifier = Modifier
                        .weight(1f)
                        .clip(RoundedCornerShape(18.dp))
                        .background(if (detailedSelected) visuals.primary.copy(alpha = 0.22f) else CelTerminalBg.copy(alpha = 0.84f))
                        .border(
                            width = if (detailedSelected) 1.6.dp else 1.dp,
                            color = if (detailedSelected) visuals.primary else CelBorderSubtle,
                            shape = RoundedCornerShape(18.dp),
                        )
                        .clickable {
                            onSelectGender("Detailed Female")
                            blinkCount++
                        }
                        .padding(10.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(112.dp)
                            .clip(RoundedCornerShape(12.dp))
                            .background(Color.Black),
                    ) {
                        DotMatrixAvatarCanvas(
                            expression = detailedExpr,
                            modifier = Modifier.fillMaxSize(),
                            scale = 0.92f,
                            blinkTrigger = if (detailedSelected) blinkCount else 0,
                            onTapped = {
                                onSelectGender("Detailed Female")
                                blinkCount++
                            },
                        )
                    }
                    Text(
                        text = "Detailed Cel",
                        style = MaterialTheme.typography.titleSmall,
                        color = if (detailedSelected) visuals.primary else CelTextPrimary,
                    )
                    Text(
                        text = "Sharp anime lashes & eyes",
                        style = MaterialTheme.typography.labelSmall,
                        color = CelLavender,
                        textAlign = TextAlign.Center,
                    )
                }
            }

            // All 5 dot-matrix styles quick selector + live interactive preview
            Text(
                text = "All Styles (Tap to Preview)",
                style = MaterialTheme.typography.labelMedium,
                color = CelLavender,
            )
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                AVATAR_GENDERS.forEach { g ->
                    FilterChip(
                        selected = selectedGender == g,
                        onClick = {
                            onSelectGender(g)
                            blinkCount++
                        },
                        label = { Text(if (g == "Chibi") "Chibi (Default)" else g, maxLines = 1, softWrap = false) },
                    )
                }
            }

            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(132.dp)
                    .clip(RoundedCornerShape(16.dp))
                    .background(Color.Black)
                    .border(1.dp, visuals.activeBorder, RoundedCornerShape(16.dp)),
            ) {
                DotMatrixAvatarCanvas(
                    expression = previewExpr,
                    modifier = Modifier.fillMaxSize(),
                    scale = 1.0f,
                    blinkTrigger = blinkCount,
                    onTapped = { blinkCount++ },
                )
            }
        }

        Spacer(Modifier.height(12.dp))

        Button(
            onClick = onContinue,
            modifier = Modifier
                .fillMaxWidth()
                .height(50.dp)
                .testTag("onboarding_avatar_continue_button"),
            shape = RoundedCornerShape(16.dp),
            colors = ButtonDefaults.buttonColors(containerColor = visuals.primary),
        ) {
            Text("Continue with $selectedGender", fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.width(8.dp))
            Icon(Icons.AutoMirrored.Rounded.ArrowForward, contentDescription = null, modifier = Modifier.size(18.dp))
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun StartupProviderStep(
    providers: List<ProviderProfileEntity>,
    onSaveProviderConfig: suspend (ProviderProfileEntity) -> Unit,
    onFetchModels: suspend (ProviderProfileEntity) -> Result<List<String>>,
    onFinish: (selectedProviderId: String) -> Unit,
) {
    val visuals = LocalCelliumVisuals.current
    val scope = rememberCoroutineScope()
    val savedList = if (providers.isNotEmpty()) providers else ProviderPresets.defaultProfiles()

    var selectedEntity by remember {
        mutableStateOf(
            savedList.firstOrNull { it.id == ProviderPresets.ID_POLLINATIONS_FREE }
                ?: ProviderCatalog.ALL.first().toEntity()
        )
    }
    var showCatalogSheet by remember { mutableStateOf(false) }

    var apiKey by remember(selectedEntity.id) { mutableStateOf(selectedEntity.apiKey) }
    var baseUrl by remember(selectedEntity.id) { mutableStateOf(selectedEntity.baseUrl) }
    var modelName by remember(selectedEntity.id) { mutableStateOf(selectedEntity.selectedModel) }
    var availableModels by remember(selectedEntity.id) { mutableStateOf(ProviderPresets.decodeModels(selectedEntity.cachedModelsJson)) }
    var modelSearch by remember(selectedEntity.id) { mutableStateOf("") }
    var showKey by remember { mutableStateOf(false) }
    var testing by remember { mutableStateOf(false) }
    var statusMsg by remember(selectedEntity.id) { mutableStateOf<String?>(null) }
    var statusError by remember(selectedEntity.id) { mutableStateOf(false) }

    GlassCard(
        modifier = Modifier.fillMaxSize(),
        highlighted = true,
        shape = RoundedCornerShape(24.dp),
    ) {
        Column(
            modifier = Modifier
                .weight(1f)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Icon(Icons.Rounded.Key, contentDescription = null, tint = visuals.primary)
                Column {
                    Text("Pick Your AI Provider", style = MaterialTheme.typography.titleLarge, color = CelTextPrimary)
                    Text(
                        "Pollinations AI (Free · No Key) works immediately, or search all ${ProviderCatalog.ALL.size}+ BYOK providers & offline .gguf AI.",
                        style = MaterialTheme.typography.bodySmall,
                        color = CelTextSecondary,
                    )
                }
            }

            // Searchable 200+ Provider Dropdown Trigger
            Surface(
                onClick = { showCatalogSheet = true },
                color = CelTerminalBg.copy(alpha = 0.85f),
                shape = RoundedCornerShape(16.dp),
                border = androidx.compose.foundation.BorderStroke(1.2.dp, visuals.primary.copy(alpha = 0.7f)),
                modifier = Modifier.fillMaxWidth().testTag("onboarding_provider_dropdown"),
            ) {
                Row(
                    modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    VectorBadgeIcon(
                        iconKey = selectedEntity.badge,
                        contentDescription = null,
                        tint = if (!selectedEntity.requiresKey) CelEmeraldThought else visuals.primary,
                        containerSize = 34.dp,
                        iconSize = 18.dp,
                    )
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            text = selectedEntity.name,
                            style = MaterialTheme.typography.titleSmall,
                            color = CelTextPrimary,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                        Text(
                            text = if (!selectedEntity.requiresKey && selectedEntity.protocol != "on_device") {
                                "Ready immediately · No API key required"
                            } else if (selectedEntity.protocol == "on_device") {
                                "100% Offline .gguf / .task models"
                            } else {
                                "Tap to search ${ProviderCatalog.ALL.size}+ providers"
                            },
                            style = MaterialTheme.typography.labelSmall,
                            color = if (!selectedEntity.requiresKey) CelEmeraldThought else CelLavender,
                        )
                    }
                    Icon(Icons.Rounded.Search, contentDescription = null, tint = visuals.primary, modifier = Modifier.size(18.dp))
                    Icon(Icons.Rounded.ArrowDropDown, contentDescription = null, tint = CelLavender)
                }
            }

            if (selectedEntity.protocol == "on_device") {
                GlassCard(shape = RoundedCornerShape(16.dp), contentPadding = 12.dp) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Icon(Icons.Rounded.Memory, contentDescription = null, tint = visuals.tertiary)
                        Text("On-Device Offline AI (.gguf & .task)", style = MaterialTheme.typography.titleSmall, color = CelTextPrimary)
                    }
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "Runs 100% offline with zero API keys. After launch, open Settings -> On-Device AI to import any .gguf (llama.cpp) or .task/.bin (MediaPipe) model with Shizuku >1.5GB RAM protection.",
                        style = MaterialTheme.typography.bodySmall,
                        color = CelTextSecondary,
                    )
                }
            } else {
                OutlinedTextField(
                    value = apiKey,
                    onValueChange = { apiKey = it },
                    label = {
                        Text(
                            if (selectedEntity.requiresKey) "${selectedEntity.name} API Key"
                            else "${selectedEntity.name} API Key (Optional · Works Free!)"
                        )
                    },
                    placeholder = {
                        Text(
                            if (selectedEntity.requiresKey) "sk-... or paste provider key" else "Leave empty to test instantly for free",
                            color = CelTextMuted,
                        )
                    },
                    singleLine = true,
                    visualTransformation = if (showKey) VisualTransformation.None else PasswordVisualTransformation(),
                    trailingIcon = {
                        IconButton(onClick = { showKey = !showKey }) {
                            Icon(
                                imageVector = if (showKey) Icons.Rounded.VisibilityOff else Icons.Rounded.Visibility,
                                contentDescription = "Toggle key visibility",
                            )
                        }
                    },
                    modifier = Modifier.fillMaxWidth().testTag("onboarding_api_key_input"),
                    shape = RoundedCornerShape(14.dp),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = visuals.primary,
                        unfocusedBorderColor = CelBorderSubtle,
                        focusedTextColor = CelTextPrimary,
                        unfocusedTextColor = CelTextPrimary,
                    ),
                )

                OutlinedTextField(
                    value = baseUrl,
                    onValueChange = { baseUrl = it },
                    label = { Text("Base URL") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(14.dp),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = visuals.primary,
                        unfocusedBorderColor = CelBorderSubtle,
                        focusedTextColor = CelTextPrimary,
                        unfocusedTextColor = CelTextPrimary,
                    ),
                )

                OutlinedTextField(
                    value = modelName,
                    onValueChange = { modelName = it },
                    label = { Text("Model ID") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth().testTag("onboarding_model_input"),
                    shape = RoundedCornerShape(14.dp),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = visuals.primary,
                        unfocusedBorderColor = CelBorderSubtle,
                        focusedTextColor = CelTextPrimary,
                        unfocusedTextColor = CelTextPrimary,
                    ),
                )

                OutlinedButton(
                    onClick = {
                        testing = true
                        statusMsg = null
                        scope.launch {
                            val draft = selectedEntity.copy(
                                apiKey = apiKey.trim(),
                                baseUrl = baseUrl.trim(),
                                selectedModel = modelName.trim(),
                            )
                            val res = onFetchModels(draft)
                            testing = false
                            res.onSuccess { fetched ->
                                if (fetched.isNotEmpty()) {
                                    availableModels = fetched
                                    if (modelName.isBlank() || modelName !in fetched) {
                                        modelName = fetched.first()
                                    }
                                }
                                statusError = false
                                statusMsg = "Key verified! Loaded all ${fetched.size} live models."
                                onSaveProviderConfig(
                                    draft.copy(
                                        selectedModel = modelName.trim().ifBlank { fetched.firstOrNull().orEmpty() },
                                        cachedModelsJson = ProviderPresets.encodeModels(fetched.ifEmpty { availableModels }),
                                    )
                                )
                            }.onFailure { err ->
                                statusError = true
                                statusMsg = err.localizedMessage ?: "Connection test failed"
                            }
                        }
                    },
                    enabled = !testing,
                    shape = RoundedCornerShape(12.dp),
                    modifier = Modifier.fillMaxWidth().testTag("onboarding_test_models_button"),
                ) {
                    if (testing) {
                        CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                    } else {
                        Icon(Icons.Rounded.Refresh, contentDescription = null, modifier = Modifier.size(16.dp))
                    }
                    Spacer(Modifier.width(6.dp))
                    Text("Ping Key & Fetch All Models")
                }

                if (statusMsg != null) {
                    Text(
                        text = statusMsg!!,
                        style = MaterialTheme.typography.bodySmall,
                        color = if (statusError) CelDangerRed else CelEmeraldThought,
                    )
                }

                if (availableModels.isNotEmpty()) {
                    val filteredAvailable = remember(availableModels, modelSearch) {
                        val q = modelSearch.trim().lowercase()
                        if (q.isEmpty()) availableModels else availableModels.filter { it.lowercase().contains(q) }
                    }
                    Text(
                        text = "Live Models (${filteredAvailable.size} / ${availableModels.size})",
                        style = MaterialTheme.typography.labelMedium,
                        color = CelLavender,
                    )
                    if (availableModels.size > 5) {
                        OutlinedTextField(
                            value = modelSearch,
                            onValueChange = { modelSearch = it },
                            placeholder = { Text("Search all ${availableModels.size} models...") },
                            leadingIcon = { Icon(Icons.Rounded.Search, contentDescription = null, modifier = Modifier.size(16.dp)) },
                            singleLine = true,
                            modifier = Modifier.fillMaxWidth(),
                            shape = RoundedCornerShape(12.dp),
                        )
                    }
                    LazyColumn(
                        modifier = Modifier.fillMaxWidth().heightIn(max = 200.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        items(filteredAvailable, key = { it }) { m ->
                            val isSel = m == modelName
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(10.dp))
                                    .background(if (isSel) visuals.primary.copy(alpha = 0.24f) else CelTerminalBg.copy(alpha = 0.72f))
                                    .border(1.dp, if (isSel) visuals.activeBorder else CelBorderSubtle, RoundedCornerShape(10.dp))
                                    .clickable { modelName = m }
                                    .padding(horizontal = 10.dp, vertical = 8.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.SpaceBetween,
                            ) {
                                Text(
                                    text = m,
                                    style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                                    color = if (isSel) CelTextPrimary else CelTextSecondary,
                                    maxLines = 2,
                                    overflow = TextOverflow.Ellipsis,
                                    modifier = Modifier.weight(1f),
                                )
                                if (isSel) {
                                    Icon(Icons.Rounded.Check, contentDescription = "Selected", tint = visuals.primary, modifier = Modifier.size(16.dp))
                                }
                            }
                        }
                    }
                }
            }
        }

        Spacer(Modifier.height(12.dp))

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            TextButton(
                onClick = { onFinish(ProviderPresets.ID_POLLINATIONS_FREE) },
                modifier = Modifier.testTag("onboarding_skip_button"),
            ) {
                Text("Use Free Default", color = CelTextSecondary)
            }
            Button(
                onClick = {
                    scope.launch {
                        onSaveProviderConfig(
                            selectedEntity.copy(
                                apiKey = apiKey.trim(),
                                baseUrl = baseUrl.trim(),
                                selectedModel = modelName.trim().ifBlank { selectedEntity.selectedModel },
                                cachedModelsJson = ProviderPresets.encodeModels(availableModels),
                                updatedAtMs = System.currentTimeMillis(),
                            )
                        )
                        onFinish(selectedEntity.id)
                    }
                },
                modifier = Modifier
                    .weight(1f)
                    .height(50.dp)
                    .testTag("onboarding_launch_button"),
                shape = RoundedCornerShape(16.dp),
                colors = ButtonDefaults.buttonColors(containerColor = visuals.primary),
            ) {
                Text("Save & Launch Cel.Cellium", fontWeight = FontWeight.SemiBold, textAlign = TextAlign.Center)
            }
        }

        Spacer(Modifier.height(6.dp))
        Text(
            text = "Tip: Cel.Cellium was most thoroughly tested with Google Gemini models.",
            style = MaterialTheme.typography.labelSmall,
            color = CelTextMuted.copy(alpha = 0.78f),
            textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth(),
        )
    }

    if (showCatalogSheet) {
        ProviderSearchDropdownSheet(
            savedProviders = savedList,
            activeProviderId = selectedEntity.id,
            onSelectCatalogProvider = { entry ->
                val existing = savedList.firstOrNull { it.id == entry.id }
                selectedEntity = existing ?: entry.toEntity()
            },
            onSelectSavedProviderModel = { pid, model ->
                val existing = savedList.firstOrNull { it.id == pid }
                if (existing != null) {
                    selectedEntity = existing.copy(selectedModel = model)
                }
            },
            onFetchActiveModels = onFetchModels,
            onOpenSettingsProviders = {},
            onDismiss = { showCatalogSheet = false },
        )
    }
}
