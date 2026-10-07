from django.urls import path

from . import views

app_name = "ipam"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),

    path("regions/", views.RegionListView.as_view(), name="region_list"),
    path("regions/new/", views.RegionCreateView.as_view(), name="region_create"),
    path("regions/<int:pk>/", views.RegionDetailView.as_view(), name="region_detail"),
    path("regions/<int:pk>/edit/", views.RegionUpdateView.as_view(), name="region_update"),
    path("regions/<int:pk>/delete/", views.RegionDeleteView.as_view(), name="region_delete"),

    path("districts/new/", views.DistrictCreateView.as_view(), name="district_create"),
    path("districts/<int:pk>/edit/", views.DistrictUpdateView.as_view(), name="district_update"),
    path("districts/<int:pk>/delete/", views.DistrictDeleteView.as_view(), name="district_delete"),

    path("branches/", views.BranchListView.as_view(), name="branch_list"),
    path("branches/new/", views.BranchCreateView.as_view(), name="branch_create"),
    path("branches/<int:pk>/", views.BranchDetailView.as_view(), name="branch_detail"),
    path("branches/<int:pk>/edit/", views.BranchUpdateView.as_view(), name="branch_update"),
    path("branches/<int:pk>/delete/", views.BranchDeleteView.as_view(), name="branch_delete"),

    path("devices/", views.DeviceListView.as_view(), name="device_list"),
    path("devices/new/", views.DeviceCreateView.as_view(), name="device_create"),
    path("devices/<int:pk>/", views.DeviceDetailView.as_view(), name="device_detail"),
    path("devices/<int:pk>/edit/", views.DeviceUpdateView.as_view(), name="device_update"),
    path("devices/<int:pk>/delete/", views.DeviceDeleteView.as_view(), name="device_delete"),

    path("subnets/", views.SubnetListView.as_view(), name="subnet_list"),
    path("subnets/new/", views.SubnetCreateView.as_view(), name="subnet_create"),
    path("subnets/<int:pk>/", views.SubnetDetailView.as_view(), name="subnet_detail"),
    path("subnets/<int:pk>/edit/", views.SubnetUpdateView.as_view(), name="subnet_update"),
    path("subnets/<int:pk>/delete/", views.SubnetDeleteView.as_view(), name="subnet_delete"),
    path("subnets/<int:subnet_pk>/ips/new/", views.IPAddressCreateView.as_view(), name="ip_create"),
    path("subnets/<int:subnet_pk>/ips/<int:pk>/edit/", views.IPAddressUpdateView.as_view(), name="ip_update"),
    path("subnets/<int:subnet_pk>/ips/<int:pk>/delete/", views.IPAddressDeleteView.as_view(), name="ip_delete"),

    path("ips/", views.IPAddressListView.as_view(), name="ip_list"),

    path("vlans/", views.VLANListView.as_view(), name="vlan_list"),
    path("vlans/new/", views.VLANCreateView.as_view(), name="vlan_create"),
    path("vlans/<int:pk>/edit/", views.VLANUpdateView.as_view(), name="vlan_update"),
    path("vlans/<int:pk>/delete/", views.VLANDeleteView.as_view(), name="vlan_delete"),

    path("vlan-types/", views.VLANTypeListView.as_view(), name="vlantype_list"),
    path("vlan-types/new/", views.VLANTypeCreateView.as_view(), name="vlantype_create"),
    path("vlan-types/<int:pk>/edit/", views.VLANTypeUpdateView.as_view(), name="vlantype_update"),
    path("vlan-types/<int:pk>/delete/", views.VLANTypeDeleteView.as_view(), name="vlantype_delete"),

    path("access/", views.AccessControlView.as_view(), name="access_control"),
    path("access/users/<int:pk>/", views.UserAccessView.as_view(), name="user_access"),
    path("audit/", views.AuditLogListView.as_view(), name="audit_list"),

    path("prices/", views.PriceListView.as_view(), name="price_list"),
    path("prices/new/", views.TariffCreateView.as_view(), name="tariff_create"),
    path("prices/<int:pk>/edit/", views.TariffUpdateView.as_view(), name="tariff_update"),
    path("prices/<int:pk>/delete/", views.TariffDeleteView.as_view(), name="tariff_delete"),

    path("leases/", views.LeaseListView.as_view(), name="lease_list"),
    path("leases/new/", views.LeaseCreateView.as_view(), name="lease_create"),
    path("leases/<int:pk>/", views.LeaseDetailView.as_view(), name="lease_detail"),
    path("leases/<int:pk>/edit/", views.LeaseUpdateView.as_view(), name="lease_update"),
    path("leases/<int:pk>/delete/", views.LeaseDeleteView.as_view(), name="lease_delete"),
    path("leases/<int:lease_pk>/payments/new/", views.PaymentCreateView.as_view(), name="payment_create"),
    path("leases/<int:lease_pk>/payments/<int:pk>/delete/", views.PaymentDeleteView.as_view(), name="payment_delete"),
]
