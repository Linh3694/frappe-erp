// Copyright (c) 2024, Linh Nguyen and contributors
// For license information, please see license.txt

frappe.ui.form.on('ERP Microsoft User', {
	refresh: function(frm) {
		// Add custom buttons
		if (!frm.doc.__islocal) {
			add_custom_buttons(frm);
		}
		
		// Set field colors based on sync status
		set_field_colors(frm);
	},
	
	sync_status: function(frm) {
		set_field_colors(frm);
	}
});

function add_custom_buttons(frm) {
	// Map to Frappe User button
	if (frm.doc.sync_status !== 'synced') {
		frm.add_custom_button(__('Map to Frappe User'), function() {
			map_to_frappe_user(frm);
		}, __('Actions'));
	}
	
	// Unmap from Frappe User button
	if (frm.doc.mapped_user_id) {
		frm.add_custom_button(__('Unmap from Frappe User'), function() {
			unmap_from_frappe_user(frm);
		}, __('Actions'));
	}
	
	// Sync from Microsoft button
	frm.add_custom_button(__('Sync from Microsoft'), function() {
		sync_from_microsoft(frm);
	}, __('Actions'));
	
	// View Mapped User button
	if (frm.doc.mapped_user_id) {
		frm.add_custom_button(__('View Mapped User'), function() {
			frappe.set_route('Form', 'User', frm.doc.mapped_user_id);
		}, __('Actions'));
	}
}

function set_field_colors(frm) {
	// Set sync status indicator color
	const status_colors = {
		'pending': 'orange',
		'synced': 'green',
		'failed': 'red',
		'deleted': 'gray'
	};
	
	const color = status_colors[frm.doc.sync_status] || 'gray';
	
	frm.set_df_property('sync_status', 'description', 
		`<span style="color: ${color}; font-weight: bold;">${frm.doc.sync_status.toUpperCase()}</span>`);
	
	// Show/hide sync error field
	frm.toggle_display('sync_error', frm.doc.sync_status === 'failed');
}

function map_to_frappe_user(frm) {
	// Show dialog to select existing user or create new one
	let d = new frappe.ui.Dialog({
		title: __('Map to Frappe User'),
		fields: [
			{
				label: __('Action'),
				fieldname: 'action',
				fieldtype: 'Select',
				options: 'Create New User\nMap to Existing User',
				default: 'Create New User',
				reqd: 1
			},
			{
				label: __('Existing User'),
				fieldname: 'existing_user',
				fieldtype: 'Link',
				options: 'User',
				depends_on: 'eval:doc.action=="Map to Existing User"'
			}
		],
		primary_action_label: __('Map User'),
		primary_action(values) {
			const user_id = values.action === 'Map to Existing User' ? values.existing_user : null;
			
			frappe.call({
				method: 'erp.user_management.doctype.erp_microsoft_user.erp_microsoft_user.map_microsoft_user_to_frappe',
				args: {
					microsoft_user_id: frm.doc.name,
					frappe_user_id: user_id
				},
				callback: function(r) {
					if (r.message && r.message.status === 'success') {
						frappe.msgprint({
							title: __('Success'),
							message: r.message.message,
							indicator: 'green'
						});
						frm.refresh();
					} else {
						frappe.msgprint({
							title: __('Error'),
							message: r.message.message || __('Mapping failed'),
							indicator: 'red'
						});
					}
				}
			});
			
			d.hide();
		}
	});
	
	d.show();
}

function unmap_from_frappe_user(frm) {
	frappe.confirm(__('Are you sure you want to unmap this Microsoft user from the Frappe user?'), function() {
		frappe.call({
			method: 'erp.user_management.doctype.erp_microsoft_user.erp_microsoft_user.unmap_microsoft_user',
			args: {
				microsoft_user_id: frm.doc.name
			},
			callback: function(r) {
				if (r.message && r.message.status === 'success') {
					frappe.msgprint({
						title: __('Success'),
						message: __('Microsoft user unmapped successfully'),
						indicator: 'green'
					});
					frm.refresh();
				}
			}
		});
	});
}

function sync_from_microsoft(frm) {
	frappe.call({
		method: 'erp.user_management.doctype.erp_microsoft_user.erp_microsoft_user.sync_microsoft_user',
		args: {
			microsoft_user_id: frm.doc.name
		},
		callback: function(r) {
			if (r.message && r.message.status === 'success') {
				frappe.msgprint({
					title: __('Success'),
					message: __('Microsoft user synced successfully'),
					indicator: 'green'
				});
				frm.refresh();
			} else {
				frappe.msgprint({
					title: __('Error'),
					message: r.message.message || __('Sync failed'),
					indicator: 'red'
				});
			}
		}
	});
}