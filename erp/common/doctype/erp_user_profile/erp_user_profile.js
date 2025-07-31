// Copyright (c) 2024, Linh Nguyen and contributors
// For license information, please see license.txt

frappe.ui.form.on('ERP User Profile', {
	refresh: function(frm) {
		// Add custom buttons
		if (!frm.doc.__islocal) {
			add_custom_buttons(frm);
		}
		
		// Set field properties
		set_field_properties(frm);
		
		// Load user information
		if (frm.doc.user) {
			load_user_info(frm);
		}
	},
	
	user: function(frm) {
		if (frm.doc.user) {
			load_user_info(frm);
		}
	},
	
	provider: function(frm) {
		toggle_auth_fields(frm);
	},
	
	active: function(frm) {
		if (!frm.doc.active) {
			frappe.msgprint({
				title: __('Warning'),
				message: __('Deactivating user will prevent them from logging in'),
				indicator: 'orange'
			});
		}
	}
});

function add_custom_buttons(frm) {
	// View User button
	frm.add_custom_button(__('View User'), function() {
		frappe.set_route('Form', 'User', frm.doc.user);
	}, __('Actions'));
	
	// Generate Reset Token button
	frm.add_custom_button(__('Generate Reset Token'), function() {
		generate_reset_token(frm);
	}, __('Actions'));
	
	// Clear Reset Token button
	if (frm.doc.reset_password_token) {
		frm.add_custom_button(__('Clear Reset Token'), function() {
			clear_reset_token(frm);
		}, __('Actions'));
	}
	
	// Update Last Seen button
	frm.add_custom_button(__('Update Last Seen'), function() {
		update_last_seen(frm);
	}, __('Actions'));
}

function set_field_properties(frm) {
	// Set field colors based on status
	if (frm.doc.active) {
		frm.set_df_property('active', 'description', 
			'<span style="color: green; font-weight: bold;">ACTIVE</span>');
	} else {
		frm.set_df_property('active', 'description', 
			'<span style="color: red; font-weight: bold;">INACTIVE</span>');
	}
	
	if (frm.doc.disabled) {
		frm.set_df_property('disabled', 'description', 
			'<span style="color: red; font-weight: bold;">DISABLED</span>');
	}
	
	// Toggle auth fields based on provider
	toggle_auth_fields(frm);
	
	// Format timestamps
	if (frm.doc.last_login) {
		frm.set_df_property('last_login', 'description', 
			`Last login: ${moment(frm.doc.last_login).fromNow()}`);
	}
	
	if (frm.doc.last_seen) {
		frm.set_df_property('last_seen', 'description', 
			`Last seen: ${moment(frm.doc.last_seen).fromNow()}`);
	}
}

function toggle_auth_fields(frm) {
	// Show/hide auth fields based on provider
	frm.toggle_display('microsoft_id', frm.doc.provider === 'microsoft');
	frm.toggle_display('apple_id', frm.doc.provider === 'apple');
}

function load_user_info(frm) {
	// Load and display user information
	frappe.db.get_doc('User', frm.doc.user)
		.then(user => {
			frm.set_df_property('user', 'description', 
				`<strong>${user.full_name}</strong><br/>
				 Email: ${user.email}<br/>
				 Enabled: ${user.enabled ? 'Yes' : 'No'}`);
		});
}

function generate_reset_token(frm) {
	frappe.confirm(__('Generate new password reset token? This will invalidate any existing token.'), function() {
		frappe.call({
			method: 'erp.user_management.doctype.erp_user_profile.erp_user_profile.generate_reset_token',
			args: {
				profile_name: frm.doc.name
			},
			callback: function(r) {
				if (r.message && r.message.status === 'success') {
					frappe.msgprint({
						title: __('Success'),
						message: __('Reset token generated: ') + r.message.token,
						indicator: 'green'
					});
					frm.refresh();
				}
			}
		});
	});
}

function clear_reset_token(frm) {
	frappe.confirm(__('Clear password reset token?'), function() {
		frappe.call({
			method: 'erp.user_management.doctype.erp_user_profile.erp_user_profile.clear_reset_token',
			args: {
				profile_name: frm.doc.name
			},
			callback: function(r) {
				if (r.message && r.message.status === 'success') {
					frappe.msgprint({
						title: __('Success'),
						message: __('Reset token cleared'),
						indicator: 'green'
					});
					frm.refresh();
				}
			}
		});
	});
}

function update_last_seen(frm) {
	frappe.call({
		method: 'erp.user_management.doctype.erp_user_profile.erp_user_profile.update_last_seen',
		args: {
			user_email: frm.doc.user
		},
		callback: function(r) {
			if (r.message && r.message.status === 'success') {
				frappe.msgprint({
					title: __('Success'),
					message: __('Last seen updated'),
					indicator: 'green'
				});
				frm.refresh();
			}
		}
	});
}